from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import uuid4
from datetime import datetime, timezone

from src.infrastructure.database import get_db
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.procurement_model import ProcurementRequestModel
from src.infrastructure.models.settings_model import SettingsModel
from src.infrastructure.models.notification_model import NotificationModel
from src.infrastructure.models.activity_model import ProcurementActivityLogModel
from src.application.dtos.response_wrapper import success_response
from src.application.dtos.deadline_dto import (
    DeadlineCreateDto,
    DeadlineUpdateDto,
    DeadlineResponseDto,
    EscalateDeadlineDto,
    RecoveryPlanDto,
)

router = APIRouter(prefix="/deadlines", tags=["Deadlines - D4 SLA"])


@router.get("")
async def get_deadlines(request_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Get all deadlines/SLA (Modul D4). Optionally filter by request_id."""
    query = select(DeadlineModel)
    if request_id:
        query = query.where(DeadlineModel.request_id == request_id)
        
    result = await db.execute(query)
    deadlines = result.scalars().all()
    
    data = [DeadlineResponseDto.model_validate(d).model_dump(mode="json") for d in deadlines]
    return success_response(data=data, message="Deadlines fetched")


@router.post("/evaluate-sla")
async def evaluate_sla(request_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """
    Evaluates SLA deadlines against target dates, operational status, and system settings.
    - Pauses evaluation if parent procurement is 'On Hold'.
    - Updates status to 'At Risk' if remaining days <= sla_warning_days.
    - Updates status to 'Overdue' if target_date < today.
    - Triggers managerial auto-escalation if overdue days >= auto_escalate_days (when auto_escalation enabled).
    - Dispatches notifications and logs audit trail for escalations.
    """
    settings_res = await db.execute(select(SettingsModel).limit(1))
    settings = settings_res.scalar_one_or_none()
    sla_warning_days = settings.sla_warning_days if settings else 3
    auto_escalation = settings.auto_escalation if settings else False
    auto_escalate_days = settings.auto_escalate_days if settings else 5
    manager_id = settings.escalation_manager_id if settings and settings.escalation_manager_id else "Manager Pengadaan"

    query = select(DeadlineModel).where(DeadlineModel.status != "Selesai")
    if request_id:
        query = query.where(DeadlineModel.request_id == request_id)
    result = await db.execute(query)
    deadlines = result.scalars().all()

    proc_ids = list({d.request_id for d in deadlines if d.request_id})
    proc_map = {}
    if proc_ids:
        proc_res = await db.execute(select(ProcurementRequestModel).where(ProcurementRequestModel.id.in_(proc_ids)))
        for p in proc_res.scalars().all():
            proc_map[p.id] = p

    now = datetime.now(timezone.utc)
    today = now.date()

    evaluated_count = len(deadlines)
    on_track_count = 0
    at_risk_count = 0
    overdue_count = 0
    escalated_count = 0
    paused_count = 0

    for d in deadlines:
        proc = proc_map.get(d.request_id)
        if proc and proc.operational_status == "On Hold":
            paused_count += 1
            continue

        target_d = d.target_date
        if hasattr(target_d, "date"):
            t_date = target_d.date()
        else:
            continue

        if t_date < today:
            overdue_days = (today - t_date).days
            d.status = "Overdue"
            overdue_count += 1

            if auto_escalation and overdue_days >= auto_escalate_days:
                if not d.is_escalated:
                    d.is_escalated = True
                    d.escalated_at = now
                    d.escalated_to = manager_id
                    escalated_count += 1

                    notif = NotificationModel(
                        request_id=d.request_id,
                        title=f"🚨 Eskalasi SLA: {d.task_name}",
                        description=f"Task '{d.task_name}' terlambat {overdue_days} hari melampaui batas SLA. Dialihkan ke {manager_id}.",
                        type="alert",
                        category="Hari Ini",
                        is_read=False
                    )
                    db.add(notif)

                    act_log = ProcurementActivityLogModel(
                        request_id=d.request_id,
                        user_id="SYSTEM",
                        user_name="PRIMA SLA Engine",
                        action="SLA_ESCALATED",
                        previous_state="Overdue",
                        new_state=f"Escalated ({manager_id})",
                        notes=f"Auto-escalated: Terlambat {overdue_days} hari (Ambang batas {auto_escalate_days} hari)."
                    )
                    db.add(act_log)
                else:
                    escalated_count += 1
        else:
            remaining_days = (t_date - today).days
            if remaining_days <= sla_warning_days:
                d.status = "At Risk"
                at_risk_count += 1
            else:
                d.status = "On Track"
                on_track_count += 1

    await db.commit()

    return success_response(
        data={
            "total_evaluated": evaluated_count,
            "on_track": on_track_count,
            "at_risk": at_risk_count,
            "overdue": overdue_count,
            "escalated": escalated_count,
            "paused": paused_count,
            "sla_warning_days": sla_warning_days,
            "auto_escalate_days": auto_escalate_days,
            "evaluated_at": now.isoformat(),
        },
        message="SLA evaluation completed successfully"
    )


@router.get("/{id}")
async def get_deadline_by_id(id: str, db: AsyncSession = Depends(get_db)):
    query = select(DeadlineModel).where(DeadlineModel.id == id)
    result = await db.execute(query)
    deadline = result.scalar_one_or_none()
    
    if not deadline:
        raise HTTPException(status_code=404, detail="Deadline not found")
        
    data = DeadlineResponseDto.model_validate(deadline).model_dump(mode="json")
    return success_response(data=data, message=f"Deadline {id} fetched")


@router.post("")
async def add_deadline(payload: DeadlineCreateDto, db: AsyncSession = Depends(get_db)):
    """Add a new SLA deadline"""
    new_id = f"D-{uuid4().hex[:8].upper()}"
    deadline = DeadlineModel(id=new_id, **payload.model_dump())
    db.add(deadline)
    await db.commit()
    await db.refresh(deadline)
    
    data = DeadlineResponseDto.model_validate(deadline).model_dump(mode="json")
    return success_response(data=data, message="Deadline added", code=201)


@router.patch("/{id}")
async def update_deadline(id: str, payload: DeadlineUpdateDto, db: AsyncSession = Depends(get_db)):
    """Update deadline details or status (On Track / At Risk / Overdue / Selesai)"""
    query = select(DeadlineModel).where(DeadlineModel.id == id)
    result = await db.execute(query)
    deadline = result.scalar_one_or_none()
    
    if not deadline:
        raise HTTPException(status_code=404, detail="Deadline not found")
        
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(deadline, key, value)
        
    await db.commit()
    await db.refresh(deadline)
    
    data = DeadlineResponseDto.model_validate(deadline).model_dump(mode="json")
    return success_response(data=data, message=f"Deadline {id} updated")


@router.post("/{id}/escalate")
async def escalate_deadline(id: str, payload: EscalateDeadlineDto, db: AsyncSession = Depends(get_db)):
    """Manually escalate a deadline to managerial level"""
    query = select(DeadlineModel).where(DeadlineModel.id == id)
    result = await db.execute(query)
    deadline = result.scalar_one_or_none()
    if not deadline:
        raise HTTPException(status_code=404, detail="Deadline not found")

    target_manager = payload.escalated_to or "Manager Pengadaan"
    now = datetime.now(timezone.utc)
    deadline.is_escalated = True
    deadline.escalated_at = now
    deadline.escalated_to = target_manager
    if payload.reason:
        deadline.overdue_reason = payload.reason

    notif = NotificationModel(
        request_id=deadline.request_id,
        title=f"🚨 Eskalasi Manajerial: {deadline.task_name}",
        description=f"Task '{deadline.task_name}' telah dieskalasi ke {target_manager}. Alasan: {payload.reason or 'Keterlambatan SLA'}.",
        type="alert",
        category="Hari Ini",
        is_read=False
    )
    db.add(notif)

    act_log = ProcurementActivityLogModel(
        request_id=deadline.request_id,
        user_id="CURRENT_USER",
        user_name=deadline.pic_name,
        action="SLA_MANUAL_ESCALATE",
        previous_state=deadline.status,
        new_state=f"Escalated ({target_manager})",
        notes=payload.reason or "Manual managerial escalation"
    )
    db.add(act_log)

    await db.commit()
    await db.refresh(deadline)

    data = DeadlineResponseDto.model_validate(deadline).model_dump(mode="json")
    return success_response(data=data, message=f"Deadline {id} escalated successfully")


@router.post("/{id}/recovery-plan")
async def submit_recovery_plan(id: str, payload: RecoveryPlanDto, db: AsyncSession = Depends(get_db)):
    """Submit an action recovery plan and target recovery date for an overdue/escalated deadline"""
    query = select(DeadlineModel).where(DeadlineModel.id == id)
    result = await db.execute(query)
    deadline = result.scalar_one_or_none()
    if not deadline:
        raise HTTPException(status_code=404, detail="Deadline not found")

    deadline.recovery_plan = payload.recovery_plan
    deadline.recovery_date = payload.recovery_date

    act_log = ProcurementActivityLogModel(
        request_id=deadline.request_id,
        user_id="CURRENT_USER",
        user_name=deadline.pic_name,
        action="RECOVERY_PLAN_SUBMITTED",
        previous_state=deadline.status,
        new_state=deadline.status,
        notes=f"Recovery Plan diajukan: '{payload.recovery_plan}' dengan target pemulihan {payload.recovery_date.strftime('%Y-%m-%d')}."
    )
    db.add(act_log)

    await db.commit()
    await db.refresh(deadline)

    data = DeadlineResponseDto.model_validate(deadline).model_dump(mode="json")
    return success_response(data=data, message=f"Recovery plan submitted for deadline {id}")

