"""
Procurement router — /api/v1/procurement (Modul D3)

All endpoints use FastAPI Depends() for use case injection.
Responses are typed Pydantic schemas — domain entities are converted inline.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from src.infrastructure.database import get_db
from src.infrastructure.models.procurement_model import ProcurementRequestModel
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.guarantee_model import GuaranteeModel
from src.infrastructure.models.document_model import DocumentModel

from src.application.dtos.response_wrapper import success_response
from src.application.dtos.procurement_schemas import (
    ProcurementRequestResponse,
    ProcurementDetailResponse,
    MilestoneResponse,
    CreateProcurementRequest,
    AssignPicRequest,
    UpdateOperationalStatusRequest,
    MoveStageRequest,
    MoveStepRequest,
    ActivityLogResponse,
    BaseUserSchema,
    DepartmentSchema,
)
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
        hold_started_at=entity.hold_started_at.isoformat() if entity.hold_started_at else None,
        total_hold_days=getattr(entity, "total_hold_days", 0.0) or 0.0,
        current_step=entity.current_step,
        department=DepartmentSchema(id=entity.department.id, name=entity.department.name),
        stage_started_at=entity.stage_started_at.isoformat(),
        is_urgent=entity.is_urgent,
        procurement_method=getattr(entity, "procurement_method", "Tender Terbuka") or "Tender Terbuka",
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


@router.get("/analytics/overview", summary="Get comprehensive procurement analytics & SLA bottleneck intelligence")
async def get_analytics_overview(db: AsyncSession = Depends(get_db)):
    """
    Computes real-time procurement performance analytics:
    1. Overall SLA Compliance metrics
    2. Department compliance ranking (% SLA on-track/completed per department)
    3. Stage/Step Bottleneck identifier (steps with highest overdue or pending load)
    4. Vendor Risk Index (scoring vendors based on guarantee compliance & claims)
    5. Method & operational status distribution
    """
    # 1. Procurements query
    proc_res = await db.execute(select(ProcurementRequestModel))
    procs = proc_res.scalars().all()

    total_procurements = len(procs)
    total_budget = sum([float(p.amount) for p in procs]) if procs else 0.0

    methods_breakdown = {}
    status_breakdown = {"On Going": 0, "On Hold": 0, "Batal": 0}
    stage_counts = {}

    for p in procs:
        m = p.procurement_method or "Tender Terbuka"
        methods_breakdown[m] = methods_breakdown.get(m, 0) + 1
        st = p.operational_status or "On Going"
        status_breakdown[st] = status_breakdown.get(st, 0) + 1
        stage_counts[p.stage] = stage_counts.get(p.stage, 0) + 1

    # 2. Deadlines query
    dl_res = await db.execute(select(DeadlineModel))
    deadlines = dl_res.scalars().all()

    total_dl = len(deadlines)
    dl_status_counts = {"On Track": 0, "At Risk": 0, "Overdue": 0, "Selesai": 0}
    escalated_count = 0
    dept_map = {}
    milestone_overdue_map = {}

    for d in deadlines:
        st = d.status if d.status in dl_status_counts else "On Track"
        dl_status_counts[st] += 1
        if d.is_escalated:
            escalated_count += 1

        dept_name = d.department_name or "Umum"
        if dept_name not in dept_map:
            dept_map[dept_name] = {"total": 0, "compliant": 0, "overdue": 0}
        dept_map[dept_name]["total"] += 1
        if st in ("On Track", "Selesai"):
            dept_map[dept_name]["compliant"] += 1
        elif st == "Overdue":
            dept_map[dept_name]["overdue"] += 1

        if st == "Overdue":
            milestone_overdue_map[d.milestone] = milestone_overdue_map.get(d.milestone, 0) + 1

    overall_compliance_rate = round(
        ((dl_status_counts["On Track"] + dl_status_counts["Selesai"]) / total_dl * 100) if total_dl > 0 else 100.0,
        1
    )

    department_compliance = []
    for dept_name, stats in dept_map.items():
        rate = round((stats["compliant"] / stats["total"] * 100) if stats["total"] > 0 else 100.0, 1)
        department_compliance.append({
            "department": dept_name,
            "total_deadlines": stats["total"],
            "compliant": stats["compliant"],
            "overdue": stats["overdue"],
            "compliance_rate": rate,
        })
    department_compliance.sort(key=lambda x: x["compliance_rate"], reverse=True)

    bottlenecks = []
    for ms, overdue_c in sorted(milestone_overdue_map.items(), key=lambda x: x[1], reverse=True)[:5]:
        bottlenecks.append({
            "milestone": ms,
            "overdue_count": overdue_c,
            "severity": "High" if overdue_c >= 2 else "Medium",
        })

    # 3. Guarantees & Vendor Risk
    guar_res = await db.execute(select(GuaranteeModel))
    guars = guar_res.scalars().all()

    vendor_map = {}
    for g in guars:
        v_name = g.vendor_name or "Vendor Tidak Terdaftar"
        if v_name not in vendor_map:
            vendor_map[v_name] = {"total_guarantees": 0, "expiring_soon": 0, "claimed": 0, "total_value": 0.0}
        vendor_map[v_name]["total_guarantees"] += 1
        vendor_map[v_name]["total_value"] += float(g.value) if g.value else 0.0
        if g.status == "Mendekati Expiry":
            vendor_map[v_name]["expiring_soon"] += 1
        elif g.status in ("Klaim Diajukan", "Klaim Selesai"):
            vendor_map[v_name]["claimed"] += 1

    vendor_risk_index = []
    for v_name, stats in vendor_map.items():
        if stats["claimed"] > 0 or stats["expiring_soon"] >= 2:
            risk = "High"
        elif stats["expiring_soon"] == 1:
            risk = "Medium"
        else:
            risk = "Low"
        vendor_risk_index.append({
            "vendor_name": v_name,
            "total_guarantees": stats["total_guarantees"],
            "total_value": stats["total_value"],
            "expiring_soon": stats["expiring_soon"],
            "claimed": stats["claimed"],
            "risk_level": risk,
        })
    vendor_risk_index.sort(key=lambda x: (x["risk_level"] == "High", x["risk_level"] == "Medium", x["total_value"]), reverse=True)

    # 4. Documents summary
    doc_res = await db.execute(select(DocumentModel))
    docs = doc_res.scalars().all()
    doc_stats = {
        "total": len(docs),
        "verified": sum(1 for d in docs if d.status == "Lulus Verifikasi"),
        "with_notes": sum(1 for d in docs if d.status == "Catatan Procurement"),
        "follow_up": sum(1 for d in docs if d.status == "Tindak Lanjut FPP"),
    }

    return success_response(
        data={
            "summary": {
                "total_procurements": total_procurements,
                "total_budget": total_budget,
                "overall_compliance_rate": overall_compliance_rate,
                "total_deadlines": total_dl,
                "overdue_deadlines": dl_status_counts["Overdue"],
                "escalated_deadlines": escalated_count,
            },
            "deadline_stats": dl_status_counts,
            "department_compliance": department_compliance,
            "bottlenecks": bottlenecks,
            "vendor_risk_index": vendor_risk_index,
            "methods_breakdown": methods_breakdown,
            "status_breakdown": status_breakdown,
            "stage_breakdown": stage_counts,
            "document_stats": doc_stats,
        },
        message="Analytics overview generated successfully"
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
        procurement_method=body.procurement_method,
        is_urgent=body.is_urgent,
    )
    return success_response(
        data=_to_response(request).model_dump(),
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
        data=_to_response(request).model_dump(),
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
        data=_to_response(request).model_dump(),
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
        data=_to_response(request).model_dump(),
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
        data=[
            ActivityLogResponse(
                id=a.id,
                request_id=a.request_id,
                action=a.action,
                user_id=a.user_id,
                user_name=a.user_name,
                previous_state=a.previous_state,
                new_state=a.new_state,
                notes=a.notes,
                created_at=a.created_at.isoformat() if a.created_at else "",
            ).model_dump()
            for a in activities
        ],
        message=f"{len(activities)} riwayat aktivitas ditemukan",
    )
