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
            stage_started_at=now,
            created_at=now,
            updated_at=now,
        )
        return await self.repo.create(request)


class MoveStepUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(self, request_id: str, step: str) -> ProcurementRequest:
        # Verify request exists
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        if existing.operational_status == "Batal":
            raise ValidationException("Request yang berstatus Batal tidak dapat dipindah tahapnya")
        return await self.repo.move_step(request_id, step)


class UpdateOperationalStatusUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(self, request_id: str, status: str, reason: Optional[str] = None) -> ProcurementRequest:
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        return await self.repo.update_operational_status(request_id, status, reason)


class GetMilestonesUseCase:
    def __init__(self, repo: PostgresProcurementRepository):
        self.repo = repo

    async def execute(self, request_id: str):
        existing = await self.repo.get_by_id(request_id)
        if not existing:
            raise NotFoundException(f"Procurement request '{request_id}' tidak ditemukan")
        return await self.repo.get_milestones(request_id)
