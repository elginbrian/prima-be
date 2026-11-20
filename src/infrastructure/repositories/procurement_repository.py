"""
Concrete PostgreSQL repository for ProcurementRequest (Modul D3)
Implements domain.repositories.ProcurementRepository using SQLAlchemy async.

Static workflow data lives in `src.domain.procurement_workflow`, ORM mapping in
`procurement_mappers` and gatekeeper rules in `procurement_gatekeeper`.
"""
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.domain.repositories import ProcurementRepository
from src.domain.entities.procurement import (
    ProcurementRequest,
    ProcurementMilestone,
    ProcurementActivityLog,
)
from src.domain.exceptions import NotFoundException, ValidationException
from src.domain.procurement_workflow import (
    DEFAULT_METHOD,
    PROCUREMENT_STEPS,
    STEP_TO_STAGE,
    steps_for_method,
    step_index,
)
from src.infrastructure.models.procurement_model import (
    ProcurementRequestModel,
    ProcurementMilestoneModel,
)
from src.infrastructure.models.workflow_stage_model import WorkflowStageModel
from src.infrastructure.models.activity_model import ProcurementActivityLogModel
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.repositories.procurement_gatekeeper import evaluate_gatekeeper
from src.infrastructure.repositories.procurement_mappers import (
    model_to_entity,
    activity_model_to_entity,
    milestone_model_to_entity,
    generate_milestones,
)


class PostgresProcurementRepository(ProcurementRepository):

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── helpers ─────────────────────────────────────────────────────────────

    async def _get_or_raise(self, id: str) -> ProcurementRequestModel:
        m = await self.session.get(ProcurementRequestModel, id)
        if not m:
            raise NotFoundException(f"Request {id} not found")
        return m

    def _log(
        self,
        request_id: str,
        user_id: str,
        user_name: str,
        action: str,
        previous_state: Optional[str],
        new_state: Optional[str],
        notes: Optional[str],
        created_at: Optional[datetime] = None,
    ) -> None:
        """Append an audit-trail entry to the current unit of work."""
        self.session.add(ProcurementActivityLogModel(
            request_id=request_id,
            user_id=user_id,
            user_name=user_name,
            action=action,
            previous_state=previous_state,
            new_state=new_state,
            notes=notes,
            created_at=created_at or datetime.now(timezone.utc),
        ))

    # ── queries ─────────────────────────────────────────────────────────────

    async def get_all(self) -> List[ProcurementRequest]:
        result = await self.session.execute(
            select(ProcurementRequestModel).order_by(ProcurementRequestModel.created_at.desc())
        )
        return [model_to_entity(m) for m in result.scalars().all()]

    async def get_by_id(self, id: str) -> Optional[ProcurementRequest]:
        result = await self.session.execute(
            select(ProcurementRequestModel).where(ProcurementRequestModel.id == id)
        )
        m = result.scalar_one_or_none()
        return model_to_entity(m) if m else None

    async def get_milestones(self, request_id: str) -> List[ProcurementMilestone]:
        result = await self.session.execute(
            select(ProcurementMilestoneModel)
            .where(ProcurementMilestoneModel.request_id == request_id)
            .order_by(ProcurementMilestoneModel.id)
        )
        return [milestone_model_to_entity(m) for m in result.scalars().all()]

    async def get_activities(self, request_id: str) -> List[ProcurementActivityLog]:
        stmt = (
            select(ProcurementActivityLogModel)
            .where(ProcurementActivityLogModel.request_id == request_id)
            .order_by(ProcurementActivityLogModel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return [activity_model_to_entity(m) for m in result.scalars().all()]

    async def check_gatekeeper(self, id: str) -> dict:
        m = await self._get_or_raise(id)
        return await evaluate_gatekeeper(self.session, m)

    # ── commands ────────────────────────────────────────────────────────────

    async def _load_db_steps_for_method(self, method: str) -> tuple[List[str], dict]:
        """Load ordered active workflow steps and step->stage mapping from DB, falling back to defaults."""
        res = await self.session.execute(
            select(WorkflowStageModel)
            .where(
                WorkflowStageModel.procurement_method == method,
                WorkflowStageModel.is_active == True,
            )
            .order_by(WorkflowStageModel.order_index, WorkflowStageModel.created_at)
        )
        rows = res.scalars().all()
        if rows:
            return [r.step_name for r in rows], {r.step_name: r.stage_group for r in rows}
        return steps_for_method(method), dict(STEP_TO_STAGE)

    async def create(self, request: ProcurementRequest) -> ProcurementRequest:
        request_id = request.id or f"REQ-{str(uuid.uuid4())[:8].upper()}"
        method = request.procurement_method or DEFAULT_METHOD
        steps, stage_map = await self._load_db_steps_for_method(method)
        current_step = request.current_step if request.current_step in steps else steps[0]
        initial_stage = stage_map.get(current_step, STEP_TO_STAGE.get(current_step, request.stage or "Sourcing"))

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

        # Generate milestones from dynamic DB workflow stages
        now = datetime.now(timezone.utc)
        curr_idx = steps.index(current_step) if current_step in steps else 0
        for i, stp in enumerate(steps):
            if i < curr_idx:
                ms_status, ms_date = "Done", now
            elif i == curr_idx:
                ms_status, ms_date = "In Progress", now
            else:
                ms_status, ms_date = "Pending", None
            self.session.add(ProcurementMilestoneModel(
                id=f"{request_id}-{str(i + 1).zfill(2)}",
                request_id=request_id,
                step=stp,
                status=ms_status,
                date=ms_date,
                pic_id=request.pic.id,
                pic_name=request.pic.name,
            ))

        self._log(
            request_id, request.pic.id, request.pic.name, "CREATE",
            previous_state=None,
            new_state=initial_stage,
            notes=f"Pengadaan baru dibuat ({method}) dengan nilai Rp {request.amount:,.0f}",
        )

        await self.session.flush()
        await self.session.refresh(model)
        return model_to_entity(model)

    async def update(self, id: str, request: ProcurementRequest) -> ProcurementRequest:
        m = await self._get_or_raise(id)
        m.title = request.title
        m.amount = request.amount
        m.stage = request.stage
        m.operational_status = request.operational_status
        m.operational_status_reason = request.operational_status_reason
        m.current_step = request.current_step
        m.is_urgent = request.is_urgent
        m.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return model_to_entity(m)

    async def move_step(
        self,
        id: str,
        step: str,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        force: bool = False,
        override_reason: Optional[str] = None,
    ) -> ProcurementRequest:
        m = await self._get_or_raise(id)
        old_step = m.current_step
        _, stage_map = await self._load_db_steps_for_method(m.procurement_method or DEFAULT_METHOD)
        new_stage = stage_map.get(step, STEP_TO_STAGE.get(step, m.stage))
        now = datetime.now(timezone.utc)

        # Determine ordering from request's actual milestones first
        ms_res = await self.session.execute(
            select(ProcurementMilestoneModel)
            .where(ProcurementMilestoneModel.request_id == id)
            .order_by(ProcurementMilestoneModel.id)
        )
        req_milestones = ms_res.scalars().all()
        req_steps = [ms.step for ms in req_milestones] if req_milestones else PROCUREMENT_STEPS

        is_moving_forward = step_index(step, req_steps, default=len(req_steps)) > step_index(old_step, req_steps, default=0)
        is_override = False

        if is_moving_forward:
            gatekeeper = await evaluate_gatekeeper(self.session, m)
            if not gatekeeper["is_ready_to_advance"]:
                if not force:
                    first_err = gatekeeper["blockers"][0]["title"]
                    raise ValidationException(
                        f"Gatekeeper Prasyarat: Tahap tidak dapat dimajukan karena kendala '{first_err}'. "
                        "Selesaikan prasyarat atau gunakan opsi force override bila memiliki otorisasi."
                    )
                is_override = True

        m.current_step = step
        m.stage = new_stage
        m.updated_at = now

        await self._sync_milestones(id, step, now)

        note_text = (
            f"Override Gatekeeper dipindahkan ke '{step}'. Alasan: {override_reason or 'Otorisasi Manager'}"
            if is_override
            else f"Langkah dipindahkan ke '{step}' (Stage: '{new_stage}')"
        )
        self._log(
            id, actor_id or m.pic_id, actor_name or m.pic_name,
            "MOVE_STEP_OVERRIDE" if is_override else "MOVE_STEP",
            previous_state=old_step, new_state=step, notes=note_text, created_at=now,
        )

        await self.session.flush()
        return model_to_entity(m)

    async def _sync_milestones(self, request_id: str, current_step: str, now: datetime) -> None:
        """Re-label every milestone as Done / In Progress / Pending relative to the request's milestone order."""
        ms_result = await self.session.execute(
            select(ProcurementMilestoneModel)
            .where(ProcurementMilestoneModel.request_id == request_id)
            .order_by(ProcurementMilestoneModel.id)
        )
        milestones = ms_result.scalars().all()
        if not milestones:
            return
        ordered_steps = [ms.step for ms in milestones]
        current_index = ordered_steps.index(current_step) if current_step in ordered_steps else -1
        if current_index < 0:
            return
        for idx, ms_model in enumerate(milestones):
            if idx < current_index:
                ms_model.status = "Done" if ms_model.status != "Skipped" else "Skipped"
                ms_model.date = ms_model.date or now
            elif idx == current_index:
                ms_model.status = "In Progress"
                ms_model.date = now
            else:
                ms_model.status = "Pending"

    async def update_milestones(
        self,
        request_id: str,
        milestones_payload: list,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> List[ProcurementMilestone]:
        """Replace/update ordered milestones for a specific procurement request (Admin/Manager edit)."""
        m = await self._get_or_raise(request_id)
        now = datetime.now(timezone.utc)

        old_res = await self.session.execute(
            select(ProcurementMilestoneModel)
            .where(ProcurementMilestoneModel.request_id == request_id)
            .order_by(ProcurementMilestoneModel.id)
        )
        old_milestones = old_res.scalars().all()
        old_summary = ", ".join(ms.step for ms in old_milestones[:5])

        for old_ms in old_milestones:
            await self.session.delete(old_ms)
        await self.session.flush()

        new_models: List[ProcurementMilestoneModel] = []
        active_step = None
        for idx, item in enumerate(milestones_payload):
            step_name = (item.step if hasattr(item, "step") else item.get("step", "")).strip()
            if not step_name:
                continue
            status = (item.status if hasattr(item, "status") else item.get("status", "Pending")) or "Pending"
            ms_notes = item.notes if hasattr(item, "notes") else item.get("notes")
            if status == "In Progress" and active_step is None:
                active_step = step_name
            ms_model = ProcurementMilestoneModel(
                id=f"{request_id}-{str(idx + 1).zfill(2)}-{uuid.uuid4().hex[:4].upper()}",
                request_id=request_id,
                step=step_name,
                status=status,
                date=now if status in ("Done", "In Progress") else None,
                pic_id=m.pic_id,
                pic_name=m.pic_name,
                notes=ms_notes,
            )
            self.session.add(ms_model)
            new_models.append(ms_model)

        if active_step:
            m.current_step = active_step
        elif new_models:
            first_pending = next((ms for ms in new_models if ms.status == "Pending"), None)
            m.current_step = first_pending.step if first_pending else new_models[-1].step
        m.updated_at = now

        self._log(
            request_id,
            actor_id or m.pic_id,
            actor_name or m.pic_name,
            "UPDATE_MILESTONES",
            previous_state=f"{len(old_milestones)} tahapan",
            new_state=f"{len(new_models)} tahapan",
            notes=notes or f"Admin memperbarui daftar tahapan pekerjaan ({len(new_models)} tahapan). Sebelumnya: {old_summary}",
            created_at=now,
        )

        await self.session.flush()
        return [milestone_model_to_entity(ms) for ms in new_models]

    async def move_stage(
        self,
        id: str,
        stage: str,
        notes: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> ProcurementRequest:
        m = await self._get_or_raise(id)
        old_stage = m.stage
        now = datetime.now(timezone.utc)
        m.stage = stage
        m.stage_started_at = now
        m.updated_at = now

        self._log(
            id, actor_id or m.pic_id, actor_name or m.pic_name, "MOVE_STAGE",
            previous_state=old_stage, new_state=stage,
            notes=notes or f"Tahap dipindahkan ke '{stage}'", created_at=now,
        )

        await self.session.flush()
        return model_to_entity(m)

    async def update_operational_status(
        self,
        id: str,
        status: str,
        reason: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> ProcurementRequest:
        m = await self._get_or_raise(id)
        old_status = m.operational_status
        now = datetime.now(timezone.utc)

        # SLA Pausing & Resuming Logic
        if status == "On Hold" and old_status != "On Hold":
            m.hold_started_at = now
        elif status == "On Going" and old_status == "On Hold" and m.hold_started_at:
            hold_days = max(1.0, round((now - m.hold_started_at).total_seconds() / 86400, 1))
            m.total_hold_days = (m.total_hold_days or 0.0) + hold_days
            m.hold_started_at = None
            await self._extend_active_deadlines(id, hold_days)

        m.operational_status = status
        m.operational_status_reason = reason
        m.updated_at = now

        self._log(
            id, actor_id or m.pic_id, actor_name or m.pic_name, "UPDATE_STATUS",
            previous_state=old_status, new_state=status,
            notes=reason or f"Status operasional diubah menjadi '{status}'", created_at=now,
        )

        await self.session.flush()
        return model_to_entity(m)

    async def _extend_active_deadlines(self, request_id: str, hold_days: float) -> None:
        """Push every unfinished deadline of the request forward by the hold duration."""
        stmt = select(DeadlineModel).where(
            DeadlineModel.request_id == request_id,
            DeadlineModel.status != "Selesai",
        )
        for dl in (await self.session.execute(stmt)).scalars().all():
            if dl.target_date:
                dl.target_date = dl.target_date + timedelta(days=int(hold_days))

    async def assign_pic(
        self,
        id: str,
        new_pic_id: str,
        new_pic_name: str,
        handover_notes: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> ProcurementRequest:
        m = await self._get_or_raise(id)

        old_pic_desc = f"{m.pic_name} ({m.pic_id})"
        new_pic_desc = f"{new_pic_name} ({new_pic_id})"
        now = datetime.now(timezone.utc)

        m.pic_id = new_pic_id
        m.pic_name = new_pic_name
        m.updated_at = now

        # Update active and pending milestones to new PIC
        stmt = select(ProcurementMilestoneModel).where(
            ProcurementMilestoneModel.request_id == id,
            ProcurementMilestoneModel.status.in_(["Pending", "In Progress"]),
        )
        for ms in (await self.session.execute(stmt)).scalars().all():
            ms.pic_id = new_pic_id
            ms.pic_name = new_pic_name

        self._log(
            id, actor_id or new_pic_id, actor_name or new_pic_name, "HANDOVER_PIC",
            previous_state=old_pic_desc, new_state=new_pic_desc,
            notes=handover_notes or f"Delegasi tugas pekerjaan ke {new_pic_name}", created_at=now,
        )

        await self.session.flush()
        return model_to_entity(m)

    async def delete(self, id: str) -> None:
        m = await self._get_or_raise(id)
        await self.session.delete(m)
        await self.session.flush()
