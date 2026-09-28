"""
Concrete PostgreSQL repository for ProcurementRequest (Modul D3)
Implements domain.repositories.ProcurementRepository using SQLAlchemy async.
"""
from typing import List, Optional
from datetime import datetime, timezone
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import selectinload

from src.domain.repositories import ProcurementRepository
from src.domain.entities.procurement import ProcurementRequest, ProcurementMilestone
from src.domain.entities.user import BaseUser, Department
from src.domain.exceptions import NotFoundException
from src.infrastructure.models.procurement_model import (
    ProcurementRequestModel,
    ProcurementMilestoneModel,
)

PROCUREMENT_STEPS = [
    "Rapat Pra-Tender",
    "Pengumuman Pengadaan",
    "Prebid Meeting",
    "Pemasukan Dokumen Penawaran",
    "Pembukaan Penawaran",
    "Evaluasi Dokumen Penawaran",
    "Sosialisasi e-Auction",
    "Negosiasi e-Auction",
    "Negosiasi Manual",
    "Laporan Hasil Pemilihan",
    "Pengumuman Pemenang",
    "Penunjukan Pemenang",
]

STEP_TO_STAGE = {
    "Rapat Pra-Tender": "Sourcing",
    "Pengumuman Pengadaan": "Sourcing",
    "Prebid Meeting": "Sourcing",
    "Pemasukan Dokumen Penawaran": "Sourcing",
    "Pembukaan Penawaran": "Evaluasi",
    "Evaluasi Dokumen Penawaran": "Evaluasi",
    "Sosialisasi e-Auction": "Evaluasi",
    "Negosiasi e-Auction": "Evaluasi",
    "Negosiasi Manual": "Evaluasi",
    "Laporan Hasil Pemilihan": "Contracting",
    "Pengumuman Pemenang": "Contracting",
    "Penunjukan Pemenang": "Selesai",
}


def _model_to_entity(m: ProcurementRequestModel) -> ProcurementRequest:
    """Convert ORM model → domain entity"""
    return ProcurementRequest(
        id=m.id,
        title=m.title,
        pic=BaseUser(id=m.pic_id, name=m.pic_name),
        fpp=BaseUser(id=m.fpp_id, name=m.fpp_name),
        amount=m.amount,
        stage=m.stage,
        operational_status=m.operational_status,
        operational_status_reason=m.operational_status_reason,
        current_step=m.current_step,
        department=Department(id=m.department_id, name=m.department_name),
        stage_started_at=m.stage_started_at,
        is_urgent=m.is_urgent,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _milestone_model_to_entity(m: ProcurementMilestoneModel) -> ProcurementMilestone:
    return ProcurementMilestone(
        id=m.id,
        request_id=m.request_id,
        step=m.step,
        status=m.status,
        document_id=m.document_id,
        date=m.date,
        pic=BaseUser(id=m.pic_id, name=m.pic_name) if m.pic_id else None,
        notes=m.notes,
    )


def _generate_milestones(request_id: str, current_step: str, pic: BaseUser) -> List[ProcurementMilestoneModel]:
    """Generate milestone rows for all steps based on current_step"""
    current_index = PROCUREMENT_STEPS.index(current_step) if current_step in PROCUREMENT_STEPS else 0
    milestones = []
    now = datetime.now(timezone.utc)
    for i, step in enumerate(PROCUREMENT_STEPS):
        if i < current_index:
            status = "Done"
            date = now
        elif i == current_index:
            status = "In Progress"
            date = now
        else:
            status = "Pending"
            date = None
        milestones.append(ProcurementMilestoneModel(
            id=f"{request_id}-{str(i + 1).zfill(2)}",
            request_id=request_id,
            step=step,
            status=status,
            date=date,
            pic_id=pic.id,
            pic_name=pic.name,
        ))
    return milestones


class PostgresProcurementRepository(ProcurementRepository):

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> List[ProcurementRequest]:
        result = await self.session.execute(
            select(ProcurementRequestModel).order_by(ProcurementRequestModel.created_at.desc())
        )
        return [_model_to_entity(m) for m in result.scalars().all()]

    async def get_by_id(self, id: str) -> Optional[ProcurementRequest]:
        result = await self.session.execute(
            select(ProcurementRequestModel).where(ProcurementRequestModel.id == id)
        )
        m = result.scalar_one_or_none()
        return _model_to_entity(m) if m else None

    async def get_milestones(self, request_id: str) -> List[ProcurementMilestone]:
        result = await self.session.execute(
            select(ProcurementMilestoneModel)
            .where(ProcurementMilestoneModel.request_id == request_id)
            .order_by(ProcurementMilestoneModel.id)
        )
        return [_milestone_model_to_entity(m) for m in result.scalars().all()]

    async def create(self, request: ProcurementRequest) -> ProcurementRequest:
        request_id = request.id or f"REQ-{str(uuid.uuid4())[:8].upper()}"
        model = ProcurementRequestModel(
            id=request_id,
            title=request.title,
            pic_id=request.pic.id,
            pic_name=request.pic.name,
            fpp_id=request.fpp.id,
            fpp_name=request.fpp.name,
            amount=request.amount,
            stage=request.stage,
            operational_status=request.operational_status,
            current_step=request.current_step,
            department_id=request.department.id,
            department_name=request.department.name,
            is_urgent=request.is_urgent,
            stage_started_at=request.stage_started_at or datetime.now(timezone.utc),
        )
        self.session.add(model)

        # Generate milestone rows
        milestones = _generate_milestones(request_id, request.current_step, request.pic)
        for ms in milestones:
            self.session.add(ms)

        await self.session.flush()
        await self.session.refresh(model)
        return _model_to_entity(model)

    async def update(self, id: str, request: ProcurementRequest) -> ProcurementRequest:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        m.title = request.title
        m.amount = request.amount
        m.stage = request.stage
        m.operational_status = request.operational_status
        m.operational_status_reason = request.operational_status_reason
        m.current_step = request.current_step
        m.is_urgent = request.is_urgent
        m.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return _model_to_entity(m)

    async def move_step(self, id: str, step: str) -> ProcurementRequest:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        new_stage = STEP_TO_STAGE.get(step, m.stage)
        m.current_step = step
        m.stage = new_stage
        m.updated_at = datetime.now(timezone.utc)

        # Update milestones
        current_index = PROCUREMENT_STEPS.index(step) if step in PROCUREMENT_STEPS else 0
        now = datetime.now(timezone.utc)
        ms_result = await self.session.execute(
            select(ProcurementMilestoneModel).where(ProcurementMilestoneModel.request_id == id)
        )
        for ms_model in ms_result.scalars().all():
            step_index = PROCUREMENT_STEPS.index(ms_model.step) if ms_model.step in PROCUREMENT_STEPS else -1
            if step_index < current_index:
                ms_model.status = "Done" if ms_model.status != "Skipped" else "Skipped"
                ms_model.date = ms_model.date or now
            elif step_index == current_index:
                ms_model.status = "In Progress"
                ms_model.date = now
            else:
                ms_model.status = "Pending"

        await self.session.flush()
        return _model_to_entity(m)

    async def update_operational_status(self, id: str, status: str, reason: Optional[str] = None) -> ProcurementRequest:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        m.operational_status = status
        m.operational_status_reason = reason
        m.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return _model_to_entity(m)

    async def delete(self, id: str) -> None:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        await self.session.delete(m)
        await self.session.flush()
