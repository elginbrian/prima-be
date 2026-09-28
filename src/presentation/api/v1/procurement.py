"""
Procurement router — /api/v1/procurement (Modul D3)

All endpoints use FastAPI Depends() for use case injection.
Responses are typed Pydantic schemas — domain entities are converted inline.
"""
from fastapi import APIRouter, Depends
from typing import List

from src.application.dtos.response_wrapper import success_response
from src.application.dtos.procurement_schemas import (
    ProcurementRequestResponse,
    ProcurementDetailResponse,
    MilestoneResponse,
    CreateProcurementRequest,
    UpdateOperationalStatusRequest,
    MoveStepRequest,
    BaseUserSchema,
    DepartmentSchema,
)
from src.application.use_cases.procurement_use_cases import (
    GetAllProcurementsUseCase,
    GetProcurementByIdUseCase,
    CreateProcurementUseCase,
    MoveStepUseCase,
    UpdateOperationalStatusUseCase,
    GetMilestonesUseCase,
)
from src.presentation.dependencies import (
    get_all_procurements_uc,
    get_procurement_by_id_uc,
    create_procurement_uc,
    move_step_uc,
    update_operational_status_uc,
    get_milestones_uc,
)

router = APIRouter(prefix="/procurement", tags=["Procurement - D3"])


def _to_response(entity) -> ProcurementRequestResponse:
    """Convert domain entity → Pydantic response schema"""
    return ProcurementRequestResponse(
        id=entity.id,
        title=entity.title,
        pic=BaseUserSchema(id=entity.pic.id, name=entity.pic.name),
        fpp=BaseUserSchema(id=entity.fpp.id, name=entity.fpp.name),
        amount=entity.amount,
        stage=entity.stage,
        operational_status=entity.operational_status,
        operational_status_reason=entity.operational_status_reason,
        current_step=entity.current_step,
        department=DepartmentSchema(id=entity.department.id, name=entity.department.name),
        stage_started_at=entity.stage_started_at.isoformat(),
        is_urgent=entity.is_urgent,
        created_at=entity.created_at.isoformat(),
        updated_at=entity.updated_at.isoformat(),
    )


@router.get("", summary="Get all procurement requests (Kanban data)")
async def get_all(
    uc: GetAllProcurementsUseCase = Depends(get_all_procurements_uc),
):
    """
    Returns all procurement requests for Kanban Board (Modul D3).
    FE query hook: useProcurements()
    """
    requests = await uc.execute()
    return success_response(
        data=[_to_response(r).model_dump() for r in requests],
        message=f"{len(requests)} procurement request ditemukan",
    )


@router.get("/{id}", summary="Get single procurement request")
async def get_by_id(
    id: str,
    uc: GetProcurementByIdUseCase = Depends(get_procurement_by_id_uc),
    milestone_uc: GetMilestonesUseCase = Depends(get_milestones_uc),
):
    """
    Returns a single procurement request with its milestones.
    FE query hook: useProcurement(id)
    """
    request = await uc.execute(id)
    milestones = await milestone_uc.execute(id)

    response = ProcurementDetailResponse(
        **_to_response(request).model_dump(),
        milestones=[
            MilestoneResponse(
                id=m.id,
                request_id=m.request_id,
                step=m.step,
                status=m.status,
                document_id=m.document_id,
                date=m.date.isoformat() if m.date else None,
                pic=BaseUserSchema(id=m.pic.id, name=m.pic.name) if m.pic else None,
                notes=m.notes,
            )
            for m in milestones
        ]
    )
    return success_response(data=response.model_dump(), message="OK")


@router.post("", summary="Create a new procurement request")
async def create(
    body: CreateProcurementRequest,
    uc: CreateProcurementUseCase = Depends(create_procurement_uc),
):
    """
    Creates a new procurement request.
    FE mutation hook: useCreateProcurement()
    """
    request = await uc.execute(
        title=body.title,
        pic_id=body.pic_id,
        pic_name=body.pic_name,
        fpp_id=body.fpp_id,
        fpp_name=body.fpp_name,
        amount=body.amount,
        department_id=body.department_id,
        department_name=body.department_name,
        stage=body.stage,
        current_step=body.current_step,
        is_urgent=body.is_urgent,
    )
    return success_response(
        data=_to_response(request).model_dump(),
        message="Procurement request berhasil dibuat",
        code=201,
    )


@router.patch("/{id}/step", summary="Move request to a specific step")
async def move_step(
    id: str,
    body: MoveStepRequest,
    uc: MoveStepUseCase = Depends(move_step_uc),
):
    """
    Advances procurement to a specific step. Stage is auto-derived from step.
    FE mutation hook: useMoveStep(id)
    """
    request = await uc.execute(id, body.step)
    return success_response(
        data=_to_response(request).model_dump(),
        message=f"Procurement dipindah ke tahap '{body.step}'",
    )


@router.patch("/{id}/operational-status", summary="Update On Going / On Hold / Batal")
async def update_operational_status(
    id: str,
    body: UpdateOperationalStatusRequest,
    uc: UpdateOperationalStatusUseCase = Depends(update_operational_status_uc),
):
    """
    Updates operational status (On Going / On Hold / Batal).
    FE mutation hook: useUpdateOperationalStatus(id)
    """
    request = await uc.execute(id, body.status, body.reason)
    return success_response(
        data=_to_response(request).model_dump(),
        message=f"Status diperbarui menjadi '{body.status}'",
    )


@router.get("/{id}/milestones", summary="Get milestones for a request")
async def get_milestones(
    id: str,
    uc: GetMilestonesUseCase = Depends(get_milestones_uc),
):
    """Returns all step milestones for a given request"""
    milestones = await uc.execute(id)
    return success_response(
        data=[
            MilestoneResponse(
                id=m.id,
                request_id=m.request_id,
                step=m.step,
                status=m.status,
                document_id=m.document_id,
                date=m.date.isoformat() if m.date else None,
                pic=BaseUserSchema(id=m.pic.id, name=m.pic.name) if m.pic else None,
                notes=m.notes,
            ).model_dump()
            for m in milestones
        ],
        message=f"{len(milestones)} milestones ditemukan",
    )
