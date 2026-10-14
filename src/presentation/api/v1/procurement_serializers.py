"""
Domain entity → Pydantic response converters for the procurement router.
"""
from src.application.dtos.procurement_schemas import (
    ProcurementRequestResponse,
    MilestoneResponse,
    ActivityLogResponse,
    BaseUserSchema,
    DepartmentSchema,
)


def to_request_response(entity) -> ProcurementRequestResponse:
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


def to_milestone_response(m) -> MilestoneResponse:
    return MilestoneResponse(
        id=m.id,
        request_id=m.request_id,
        step=m.step,
        status=m.status,
        document_id=m.document_id,
        date=m.date.isoformat() if m.date else None,
        pic=BaseUserSchema(id=m.pic.id, name=m.pic.name) if m.pic else None,
        notes=m.notes,
    )


def to_activity_response(a) -> ActivityLogResponse:
    return ActivityLogResponse(
        id=a.id,
        request_id=a.request_id,
        action=a.action,
        user_id=a.user_id,
        user_name=a.user_name,
        previous_state=a.previous_state,
        new_state=a.new_state,
        notes=a.notes,
        created_at=a.created_at.isoformat() if a.created_at else "",
    )
