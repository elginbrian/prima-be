"""
Concrete PostgreSQL repository for ProcurementRequest (Modul D3)
Implements domain.repositories.ProcurementRepository using SQLAlchemy async.
"""
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import selectinload

from src.domain.repositories import ProcurementRepository
from src.domain.entities.procurement import (
    ProcurementRequest,
    ProcurementMilestone,
    ProcurementActivityLog,
)
from src.domain.entities.user import BaseUser, Department
from src.domain.exceptions import NotFoundException
from src.infrastructure.models.procurement_model import (
    ProcurementRequestModel,
    ProcurementMilestoneModel,
)
from src.infrastructure.models.activity_model import ProcurementActivityLogModel
from src.infrastructure.models.deadline_model import DeadlineModel

METHOD_STEPS = {
    "Tender Terbuka": [
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
    ],
    "Pemilihan Langsung": [
        "Rapat Pra-Tender",
        "Undangan Pemilihan",
        "Pemasukan Dokumen Penawaran",
        "Pembukaan & Evaluasi Penawaran",
        "Klarifikasi & Negosiasi Teknis",
        "Laporan Hasil Pemilihan",
        "Penetapan Pemenang",
        "Penunjukan Pemenang",
    ],
    "Penunjukan Langsung": [
        "Undangan Penunjukan Langsung",
        "Pemasukan & Evaluasi Dokumen",
        "Klarifikasi & Negosiasi Harga",
        "Penunjukan Pemenang",
    ],
}

PROCUREMENT_STEPS = METHOD_STEPS["Tender Terbuka"]

STEP_TO_STAGE = {
    # Tender Terbuka
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
    # Pemilihan Langsung additions
    "Undangan Pemilihan": "Sourcing",
    "Pembukaan & Evaluasi Penawaran": "Evaluasi",
    "Klarifikasi & Negosiasi Teknis": "Evaluasi",
    "Penetapan Pemenang": "Contracting",
    # Penunjukan Langsung additions
    "Undangan Penunjukan Langsung": "Sourcing",
    "Pemasukan & Evaluasi Dokumen": "Evaluasi",
    "Klarifikasi & Negosiasi Harga": "Evaluasi",
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
        hold_started_at=m.hold_started_at,
        total_hold_days=m.total_hold_days or 0.0,
        procurement_method=getattr(m, "procurement_method", "Tender Terbuka") or "Tender Terbuka",
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _activity_model_to_entity(m: ProcurementActivityLogModel) -> ProcurementActivityLog:
    return ProcurementActivityLog(
        id=m.id,
        request_id=m.request_id,
        action=m.action,
        user_id=m.user_id,
        user_name=m.user_name,
        previous_state=m.previous_state,
        new_state=m.new_state,
        notes=m.notes,
        created_at=m.created_at,
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


def _generate_milestones(
    request_id: str,
    current_step: str,
    pic: BaseUser,
    method: str = "Tender Terbuka",
) -> List[ProcurementMilestoneModel]:
    """Generate milestone rows for all steps based on method and current_step"""
    steps = METHOD_STEPS.get(method, METHOD_STEPS["Tender Terbuka"])
    current_index = steps.index(current_step) if current_step in steps else 0
    milestones = []
    now = datetime.now(timezone.utc)
    for i, step in enumerate(steps):
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
        method = request.procurement_method or "Tender Terbuka"
        steps = METHOD_STEPS.get(method, METHOD_STEPS["Tender Terbuka"])
        current_step = request.current_step if request.current_step in steps else steps[0]
        initial_stage = STEP_TO_STAGE.get(current_step, request.stage or "Sourcing")

        model = ProcurementRequestModel(
            id=request_id,
            title=request.title,
            pic_id=request.pic.id,
            pic_name=request.pic.name,
            fpp_id=request.fpp.id,
            fpp_name=request.fpp.name,
            amount=request.amount,
            stage=initial_stage,
            operational_status=request.operational_status,
            current_step=current_step,
            department_id=request.department.id,
            department_name=request.department.name,
            is_urgent=request.is_urgent,
            procurement_method=method,
            stage_started_at=request.stage_started_at or datetime.now(timezone.utc),
        )
        self.session.add(model)

        # Generate milestone rows
        milestones = _generate_milestones(request_id, current_step, request.pic, method)
        for ms in milestones:
            self.session.add(ms)

        # Record activity log
        log_entry = ProcurementActivityLogModel(
            request_id=request_id,
            user_id=request.pic.id,
            user_name=request.pic.name,
            action="CREATE",
            previous_state=None,
            new_state=initial_stage,
            notes=f"Pengadaan baru dibuat ({method}) dengan nilai Rp {request.amount:,.0f}",
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(log_entry)

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

    async def check_gatekeeper(self, id: str) -> dict:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")

        from src.infrastructure.models.document_model import DocumentModel
        from src.infrastructure.models.guarantee_model import GuaranteeModel

        blockers = []
        warnings = []

        # 1. Operational status check
        if m.operational_status == "On Hold":
            blockers.append({
                "category": "HOLD",
                "title": "Pengadaan Sedang On Hold",
                "description": "Pengadaan berstatus 'On Hold'. Ubah status operasional ke 'On Going' terlebih dahulu untuk melanjutkan.",
                "severity": "ERROR"
            })
        elif m.operational_status == "Batal":
            blockers.append({
                "category": "HOLD",
                "title": "Pengadaan Dibatalkan",
                "description": "Pengadaan berstatus 'Batal' dan tidak dapat melanjutkan tahapan.",
                "severity": "ERROR"
            })

        # 2. Document verification check
        doc_res = await self.session.execute(
            select(DocumentModel).where(DocumentModel.request_id == id)
        )
        docs = doc_res.scalars().all()

        mandatory_docs = [d for d in docs if d.type == "Wajib" or getattr(d, "document_kind", None) == "Wajib"]
        verified_mandatory = [d for d in mandatory_docs if d.status == "Lulus Verifikasi"]

        # Check unverified mandatory documents
        for doc in mandatory_docs:
            if doc.status == "Tindak Lanjut FPP":
                blockers.append({
                    "category": "DOCUMENT",
                    "title": f"Dokumen Wajib '{doc.name}' Ditolak / Perlu Revisi",
                    "description": f"Dokumen berstatus '{doc.status}' dan memiliki {len(doc.issues or [])} catatan review yang harus diperbaiki FPP.",
                    "severity": "ERROR"
                })
            elif doc.status != "Lulus Verifikasi":
                warnings.append({
                    "category": "DOCUMENT",
                    "title": f"Dokumen '{doc.name}' Belum Terverifikasi",
                    "description": f"Status dokumen saat ini: '{doc.status}'. Pastikan dokumen diverifikasi sebelum tahap evaluasi.",
                    "severity": "WARNING"
                })

        curr_idx = PROCUREMENT_STEPS.index(m.current_step) if m.current_step in PROCUREMENT_STEPS else 0
        if curr_idx >= 4 and len(mandatory_docs) == 0:
            warnings.append({
                "category": "DOCUMENT",
                "title": "Dokumen Prasyarat Wajib Belum Diunggah",
                "description": "Tahap ini mensyaratkan dokumen pengadaan (DP3 / Kerangka Acuan) yang sah.",
                "severity": "WARNING"
            })

        # 3. Guarantee check at Contracting / Selesai stages
        if curr_idx >= 9:
            guar_res = await self.session.execute(
                select(GuaranteeModel).where(GuaranteeModel.request_id == id)
            )
            guarantees = guar_res.scalars().all()
            perf_guars = [g for g in guarantees if "pelaksanaan" in (g.type or "").lower()]
            if not perf_guars:
                warnings.append({
                    "category": "GUARANTEE",
                    "title": "Jaminan Pelaksanaan Belum Didaftarkan",
                    "description": "Tahap penetapan pemenang kontrak mensyaratkan warkat Jaminan Pelaksanaan yang sah.",
                    "severity": "WARNING"
                })
            else:
                for pg in perf_guars:
                    if pg.status == "Expired":
                        blockers.append({
                            "category": "GUARANTEE",
                            "title": f"Jaminan Pelaksanaan {pg.reference_no} Sudah Expired",
                            "description": "Warkat jaminan telah melewati batas jatuh tempo. Wajib diperpanjang sebelum penunjukan pemenang.",
                            "severity": "ERROR"
                        })
                    elif pg.value < (m.amount * 0.05):
                        warnings.append({
                            "category": "GUARANTEE",
                            "title": f"Nilai Jaminan {pg.reference_no} Kurang dari 5%",
                            "description": f"Nilai jaminan (Rp {pg.value:,.0f}) di bawah 5% pagu kontrak (Rp {m.amount * 0.05:,.0f}).",
                            "severity": "WARNING"
                        })

        return {
            "request_id": id,
            "current_stage": m.stage,
            "current_step": m.current_step,
            "is_ready_to_advance": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
            "mandatory_documents_total": len(mandatory_docs),
            "mandatory_documents_verified": len(verified_mandatory),
            "can_override": True,
        }

    async def move_step(
        self,
        id: str,
        step: str,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        force: bool = False,
        override_reason: Optional[str] = None,
    ) -> ProcurementRequest:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        old_step = m.current_step
        new_stage = STEP_TO_STAGE.get(step, m.stage)
        now = datetime.now(timezone.utc)

        # Gatekeeper check if moving forward
        old_idx = PROCUREMENT_STEPS.index(old_step) if old_step in PROCUREMENT_STEPS else 0
        new_idx = PROCUREMENT_STEPS.index(step) if step in PROCUREMENT_STEPS else 0
        is_moving_forward = new_idx > old_idx
        is_override = False

        if is_moving_forward:
            gatekeeper = await self.check_gatekeeper(id)
            if not gatekeeper["is_ready_to_advance"]:
                if not force:
                    first_err = gatekeeper["blockers"][0]["title"]
                    raise ValidationException(
                        f"Gatekeeper Prasyarat: Tahap tidak dapat dimajukan karena kendala '{first_err}'. "
                        "Selesaikan prasyarat atau gunakan opsi force override bila memiliki otorisasi."
                    )
                else:
                    is_override = True

        m.current_step = step
        m.stage = new_stage
        m.updated_at = now

        # Update milestones
        current_index = PROCUREMENT_STEPS.index(step) if step in PROCUREMENT_STEPS else 0
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

        action_name = "MOVE_STEP_OVERRIDE" if is_override else "MOVE_STEP"
        note_text = (
            f"Override Gatekeeper dipindahkan ke '{step}'. Alasan: {override_reason or 'Otorisasi Manager'}"
            if is_override
            else f"Langkah dipindahkan ke '{step}' (Stage: '{new_stage}')"
        )

        log_entry = ProcurementActivityLogModel(
            request_id=id,
            user_id=actor_id or m.pic_id,
            user_name=actor_name or m.pic_name,
            action=action_name,
            previous_state=old_step,
            new_state=step,
            notes=note_text,
            created_at=now,
        )
        self.session.add(log_entry)

        await self.session.flush()
        return _model_to_entity(m)

    async def move_stage(
        self,
        id: str,
        stage: str,
        notes: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> ProcurementRequest:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        old_stage = m.stage
        now = datetime.now(timezone.utc)
        m.stage = stage
        m.stage_started_at = now
        m.updated_at = now

        log_entry = ProcurementActivityLogModel(
            request_id=id,
            user_id=actor_id or m.pic_id,
            user_name=actor_name or m.pic_name,
            action="MOVE_STAGE",
            previous_state=old_stage,
            new_state=stage,
            notes=notes or f"Tahap dipindahkan ke '{stage}'",
            created_at=now,
        )
        self.session.add(log_entry)

        await self.session.flush()
        return _model_to_entity(m)

    async def update_operational_status(
        self,
        id: str,
        status: str,
        reason: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> ProcurementRequest:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        old_status = m.operational_status
        now = datetime.now(timezone.utc)

        # SLA Pausing & Resuming Logic
        if status == "On Hold" and old_status != "On Hold":
            m.hold_started_at = now
        elif status == "On Going" and old_status == "On Hold":
            if m.hold_started_at:
                hold_seconds = (now - m.hold_started_at).total_seconds()
                hold_days = max(1.0, round(hold_seconds / 86400, 1))
                m.total_hold_days = (m.total_hold_days or 0.0) + hold_days
                m.hold_started_at = None

                # Automatically extend all active deadlines for this procurement
                stmt = select(DeadlineModel).where(
                    DeadlineModel.request_id == id,
                    DeadlineModel.status != "Selesai",
                )
                dl_result = await self.session.execute(stmt)
                for dl in dl_result.scalars().all():
                    if dl.target_date:
                        dl.target_date = dl.target_date + timedelta(days=int(hold_days))

        m.operational_status = status
        m.operational_status_reason = reason
        m.updated_at = now

        log_entry = ProcurementActivityLogModel(
            request_id=id,
            user_id=actor_id or m.pic_id,
            user_name=actor_name or m.pic_name,
            action="UPDATE_STATUS",
            previous_state=old_status,
            new_state=status,
            notes=reason or f"Status operasional diubah menjadi '{status}'",
            created_at=now,
        )
        self.session.add(log_entry)

        await self.session.flush()
        return _model_to_entity(m)

    async def assign_pic(
        self,
        id: str,
        new_pic_id: str,
        new_pic_name: str,
        handover_notes: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> ProcurementRequest:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")

        old_pic_desc = f"{m.pic_name} ({m.pic_id})"
        new_pic_desc = f"{new_pic_name} ({new_pic_id})"
        now = datetime.now(timezone.utc)

        m.pic_id = new_pic_id
        m.pic_name = new_pic_name
        m.updated_at = now

        # Update active and pending milestones to new PIC
        stmt = (
            select(ProcurementMilestoneModel)
            .where(
                ProcurementMilestoneModel.request_id == id,
                ProcurementMilestoneModel.status.in_(["Pending", "In Progress"]),
            )
        )
        milestones = (await self.session.execute(stmt)).scalars().all()
        for ms in milestones:
            ms.pic_id = new_pic_id
            ms.pic_name = new_pic_name

        # Record activity log
        log_entry = ProcurementActivityLogModel(
            request_id=id,
            user_id=actor_id or new_pic_id,
            user_name=actor_name or new_pic_name,
            action="HANDOVER_PIC",
            previous_state=old_pic_desc,
            new_state=new_pic_desc,
            notes=handover_notes or f"Delegasi tugas pekerjaan ke {new_pic_name}",
            created_at=now,
        )
        self.session.add(log_entry)

        await self.session.flush()
        return _model_to_entity(m)

    async def get_activities(self, request_id: str) -> List[ProcurementActivityLog]:
        stmt = (
            select(ProcurementActivityLogModel)
            .where(ProcurementActivityLogModel.request_id == request_id)
            .order_by(ProcurementActivityLogModel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return [_activity_model_to_entity(m) for m in result.scalars().all()]

    async def delete(self, id: str) -> None:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        await self.session.delete(m)
        await self.session.flush()
