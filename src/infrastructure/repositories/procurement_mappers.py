"""
ORM model <-> domain entity mappers and milestone factory for Procurement (Modul D3).
"""
from datetime import datetime, timezone
from typing import List

from src.domain.entities.procurement import (
    ProcurementRequest,
    ProcurementMilestone,
    ProcurementActivityLog,
)
from src.domain.entities.user import BaseUser, Department
from src.domain.procurement_workflow import DEFAULT_METHOD, steps_for_method
from src.infrastructure.models.procurement_model import (
    ProcurementRequestModel,
    ProcurementMilestoneModel,
)
from src.infrastructure.models.activity_model import ProcurementActivityLogModel


def model_to_entity(m: ProcurementRequestModel) -> ProcurementRequest:
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
        procurement_method=getattr(m, "procurement_method", DEFAULT_METHOD) or DEFAULT_METHOD,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def activity_model_to_entity(m: ProcurementActivityLogModel) -> ProcurementActivityLog:
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


def milestone_model_to_entity(m: ProcurementMilestoneModel) -> ProcurementMilestone:
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


def generate_milestones(
    request_id: str,
    current_step: str,
    pic: BaseUser,
    method: str = DEFAULT_METHOD,
) -> List[ProcurementMilestoneModel]:
    """Generate milestone rows for all steps based on method and current_step"""
    steps = steps_for_method(method)
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
