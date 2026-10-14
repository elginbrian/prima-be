"""
Procurement router — /api/v1/procurement (Modul D3)

All endpoints use FastAPI Depends() for use case injection.
Responses are typed Pydantic schemas — conversion lives in `procurement_serializers`,
analytics aggregation in `application.services.procurement_analytics`.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import get_db

from src.application.dtos.response_wrapper import success_response
from src.application.dtos.procurement_schemas import (
    ProcurementDetailResponse,
    CreateProcurementRequest,
    AssignPicRequest,
    UpdateOperationalStatusRequest,
    MoveStageRequest,
    MoveStepRequest,
)
from src.application.services.procurement_analytics import build_analytics_overview
from src.application.use_cases.procurement_use_cases import (
    GetAllProcurementsUseCase,
    GetProcurementByIdUseCase,
    CreateProcurementUseCase,
    MoveStepUseCase,
    MoveStageUseCase,
    UpdateOperationalStatusUseCase,
    GetMilestonesUseCase,
    GetActivitiesUseCase,
    CheckGatekeeperUseCase,
    AssignPicUseCase,
)
from src.presentation.api.v1.procurement_serializers import (
    to_request_response,
    to_milestone_response,
    to_activity_response,
)
from src.presentation.dependencies import (
    get_all_procurements_uc,
    get_procurement_by_id_uc,
    create_procurement_uc,
    move_step_uc,
    move_stage_uc,
    update_operational_status_uc,
    get_milestones_uc,
    get_activities_uc,
    check_gatekeeper_uc,
    assign_pic_uc,
)

router = APIRouter(prefix="/procurement", tags=["Procurement - D3"])


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
        data=[to_request_response(r).model_dump() for r in requests],
        message=f"{len(requests)} procurement request ditemukan",
    )


# NOTE: must be declared before "/{id}" so "analytics" is not captured as an id.
@router.get("/analytics/overview", summary="Get comprehensive procurement analytics & SLA bottleneck intelligence")
async def get_analytics_overview(db: AsyncSession = Depends(get_db)):
    """
    Real-time procurement performance analytics: SLA compliance, department ranking,
    stage bottlenecks, vendor risk index and method/status distribution.
    FE query hook: useProcurementAnalytics()
    """
    return success_response(
        data=await build_analytics_overview(db),
        message="Analytics overview generated successfully",
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
        **to_request_response(request).model_dump(),
        milestones=[to_milestone_response(m) for m in milestones],
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
        procurement_method=body.procurement_method,
        is_urgent=body.is_urgent,
    )
    return success_response(
        data=to_request_response(request).model_dump(),
        message="Procurement request berhasil dibuat",
        code=201,
    )


@router.patch("/{id}/stage", summary="Move request to a specific stage")
async def move_stage(
    id: str,
    body: MoveStageRequest,
    uc: MoveStageUseCase = Depends(move_stage_uc),
):
    """
    Moves procurement to a specific stage (e.g. Persiapan, Sourcing, Evaluasi, Contracting, Selesai).
    FE mutation hook: useMoveStage(id)
    """
    request = await uc.execute(id, body.stage, body.notes)
    return success_response(
        data=to_request_response(request).model_dump(),
        message=f"Procurement stage dipindah ke '{body.stage}'",
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
    request = await uc.execute(
        id,
        body.step,
        force=body.force,
        override_reason=body.override_reason,
    )
    return success_response(
        data=to_request_response(request).model_dump(),
        message=f"Procurement dipindah ke tahap '{body.step}'",
    )


@router.get("/{id}/gatekeeper", summary="Check gatekeeper readiness for a request")
async def get_gatekeeper(
    id: str,
    uc: CheckGatekeeperUseCase = Depends(check_gatekeeper_uc),
):
    """Checks whether procurement request is ready to advance without blockers."""
    result = await uc.execute(id)
    return success_response(data=result, message="Gatekeeper check evaluated")


@router.patch("/{id}/assign-pic", summary="Handover / delegasi PIC pengadaan")
async def assign_pic(
    id: str,
    body: AssignPicRequest,
    uc: AssignPicUseCase = Depends(assign_pic_uc),
):
    """
    Handover / delegasi PIC pengadaan ke personel baru dan mencatat ke log audit.
    FE mutation hook: useAssignPic()
    """
    request = await uc.execute(
        request_id=id,
        new_pic_id=body.new_pic_id,
        new_pic_name=body.new_pic_name,
        handover_notes=body.handover_notes,
    )
    return success_response(
        data=to_request_response(request).model_dump(),
        message=f"PIC berhasil dialihkan ke '{body.new_pic_name}'",
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
        data=to_request_response(request).model_dump(),
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
        data=[to_milestone_response(m).model_dump() for m in milestones],
        message=f"{len(milestones)} milestones ditemukan",
    )


@router.get("/{id}/activities", summary="Get activity log / audit trail for a procurement request")
async def get_activities(
    id: str,
    uc: GetActivitiesUseCase = Depends(get_activities_uc),
):
    """
    Returns full audit trail & activity history for a procurement request (Modul D3).
    FE query hook: useProcurementActivities(id)
    """
    activities = await uc.execute(id)
    return success_response(
        data=[to_activity_response(a).model_dump() for a in activities],
        message=f"{len(activities)} riwayat aktivitas ditemukan",
    )
