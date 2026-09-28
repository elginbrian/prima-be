"""
Dependency injection for all use cases.
Follows FastAPI's Depends() pattern — each request gets a scoped DB session.
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import get_db
from src.infrastructure.repositories.procurement_repository import PostgresProcurementRepository
from src.application.use_cases.procurement_use_cases import (
    GetAllProcurementsUseCase,
    GetProcurementByIdUseCase,
    CreateProcurementUseCase,
    MoveStepUseCase,
    UpdateOperationalStatusUseCase,
    GetMilestonesUseCase,
)


# ─── Repository factory ───────────────────────────────────────────────────────

def get_procurement_repo(session: AsyncSession = Depends(get_db)) -> PostgresProcurementRepository:
    return PostgresProcurementRepository(session)


# ─── Procurement use case factories ──────────────────────────────────────────

def get_all_procurements_uc(
    repo: PostgresProcurementRepository = Depends(get_procurement_repo),
) -> GetAllProcurementsUseCase:
    return GetAllProcurementsUseCase(repo)


def get_procurement_by_id_uc(
    repo: PostgresProcurementRepository = Depends(get_procurement_repo),
) -> GetProcurementByIdUseCase:
    return GetProcurementByIdUseCase(repo)


def create_procurement_uc(
    repo: PostgresProcurementRepository = Depends(get_procurement_repo),
) -> CreateProcurementUseCase:
    return CreateProcurementUseCase(repo)


def move_step_uc(
    repo: PostgresProcurementRepository = Depends(get_procurement_repo),
) -> MoveStepUseCase:
    return MoveStepUseCase(repo)


def update_operational_status_uc(
    repo: PostgresProcurementRepository = Depends(get_procurement_repo),
) -> UpdateOperationalStatusUseCase:
    return UpdateOperationalStatusUseCase(repo)


def get_milestones_uc(
    repo: PostgresProcurementRepository = Depends(get_procurement_repo),
) -> GetMilestonesUseCase:
    return GetMilestonesUseCase(repo)
