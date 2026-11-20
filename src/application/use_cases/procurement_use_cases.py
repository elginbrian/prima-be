"""
Procurement Use Cases — business logic orchestration for Modul D3

Each use case receives a repository, calls domain logic, returns domain entity.
Presentation layer (router) converts domain entity → Pydantic response schema.
"""
from typing import List, Optional
from datetime import datetime, timezone
import uuid

from src.domain.entities.procurement import ProcurementRequest
from src.domain.entities.user import BaseUser, Department
from src.domain.exceptions import NotFoundException, ValidationException
from src.infrastructure.integrations import (
    n8n_webhook_service,
    serialize_procurement_payload,
)
from src.infrastructure.repositories.procurement_repository import PostgresProcurementRepository


class GetAllProcurementsUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(self) -> List[ProcurementRequest]:
        return await self.repo.get_all()


class GetProcurementByIdUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(self, id: str) -> ProcurementRequest:
        request = await self.repo.get_by_id(id)
        if not request:
            raise NotFoundException(f"Procurement request '{id}' tidak ditemukan")
        return request


class CreateProcurementUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(
        self,
        title: str,
        pic_id: str,
        pic_name: str,
        fpp_id: str,
        fpp_name: str,
        amount: float,
        department_id: str,
        department_name: str,
        stage: str = "Persiapan",
        current_step: str = "Rapat Pra-Tender",
        procurement_method: Optional[str] = "Tender Terbuka",
        is_urgent: bool = False,
    ) -> ProcurementRequest:
        now = datetime.now(timezone.utc)
        request = ProcurementRequest(
            id=f"REQ-{str(uuid.uuid4())[:8].upper()}",
            title=title,
            pic=BaseUser(id=pic_id, name=pic_name),
            fpp=BaseUser(id=fpp_id, name=fpp_name),
            amount=amount,
            stage=stage,
            operational_status="On Going",
            current_step=current_step,
            department=Department(id=department_id, name=department_name),
            is_urgent=is_urgent,
            procurement_method=procurement_method or "Tender Terbuka",
            stage_started_at=now,
            created_at=now,
            updated_at=now,
        )
        created = await self.repo.create(request)
        n8n_webhook_service.emit(
            "procurement.created",
            serialize_procurement_payload(created),
            actor={"id": pic_id, "name": pic_name},
        )
        return created


class MoveStepUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(
        self,
        request_id: str,
        step: str,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        force: bool = False,
        override_reason: Optional[str] = None,
    ) -> ProcurementRequest:
        # Verify request exists
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        if existing.operational_status == "Batal":
            raise ValidationException("Request yang berstatus Batal tidak dapat dipindah tahapnya")
        updated = await self.repo.move_step(
            request_id,
            step,
            actor_id,
            actor_name,
            force=force,
            override_reason=override_reason,
        )
        n8n_webhook_service.emit(
            "procurement.stage_changed",
            serialize_procurement_payload(
                updated,
                extra={
                    "previous_stage": existing.stage,
                    "previous_step": existing.current_step,
                    "new_stage": updated.stage,
                    "new_step": updated.current_step,
                },
            ),
            actor={"id": actor_id, "name": actor_name or "PRIMA User"},
        )
        return updated


class MoveStageUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(
        self,
        request_id: str,
        stage: str,
        notes: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> ProcurementRequest:
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        if existing.operational_status == "Batal":
            raise ValidationException("Request yang berstatus Batal tidak dapat dipindah tahapnya")
        updated = await self.repo.move_stage(request_id, stage, notes, actor_id, actor_name)
        n8n_webhook_service.emit(
            "procurement.stage_changed",
            serialize_procurement_payload(
                updated,
                extra={
                    "previous_stage": existing.stage,
                    "previous_step": existing.current_step,
                    "new_stage": updated.stage,
                    "new_step": updated.current_step,
                    "notes": notes,
                },
            ),
            actor={"id": actor_id, "name": actor_name or "PRIMA User"},
        )
        return updated


class UpdateOperationalStatusUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(
        self,
        request_id: str,
        status: str,
        reason: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> ProcurementRequest:
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        updated = await self.repo.update_operational_status(request_id, status, reason, actor_id, actor_name)
        n8n_webhook_service.emit(
            "procurement.status_changed",
            serialize_procurement_payload(
                updated,
                extra={
                    "previous_status": existing.operational_status,
                    "new_status": updated.operational_status,
                    "reason": reason,
                },
            ),
            actor={"id": actor_id, "name": actor_name or "PRIMA User"},
        )
        return updated


class GetMilestonesUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(self, request_id: str):
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        return await self.repo.get_milestones(request_id)


class GetActivitiesUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(self, request_id: str):
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        return await self.repo.get_activities(request_id)


class CheckGatekeeperUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(self, request_id: str):
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        return await self.repo.check_gatekeeper(request_id)


class AssignPicUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(
        self,
        request_id: str,
        new_pic_id: str,
        new_pic_name: str,
        handover_notes: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ):
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        updated = await self.repo.assign_pic(
            id=request_id,
            new_pic_id=new_pic_id,
            new_pic_name=new_pic_name,
            handover_notes=handover_notes,
            actor_id=actor_id,
            actor_name=actor_name,
        )
        n8n_webhook_service.emit(
            "procurement.pic_assigned",
            serialize_procurement_payload(
                updated,
                extra={
                    "previous_pic_id": getattr(existing.pic, "id", None),
                    "previous_pic_name": getattr(existing.pic, "name", None),
                    "new_pic_id": new_pic_id,
                    "new_pic_name": new_pic_name,
                    "handover_notes": handover_notes,
                },
            ),
            actor={"id": actor_id, "name": actor_name or "PRIMA User"},
        )
        return updated


class UpdateMilestonesUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(
        self,
        request_id: str,
        milestones_payload: list,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        notes: Optional[str] = None,
    ):
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        if not milestones_payload:
            raise ValidationException("Daftar tahapan pekerjaan tidak boleh kosong")
        return await self.repo.update_milestones(
            request_id=request_id,
            milestones_payload=milestones_payload,
            actor_id=actor_id,
            actor_name=actor_name,
            notes=notes,
        )
