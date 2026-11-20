"""
Document Validation Use Cases (Modul D1 & Audit Trail D2/D3/D4)

Handles:
1. AI document analysis against checklist items and prompt.
2. Publishing validated documents and extracted stages directly into the Tracker as a new Procurement Request.
3. Fetching historical validation logs for compliance and audit trail.
"""
import asyncio
import io
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_, func

from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models.validation_model import DocumentValidationLogModel, ValidationProfileModel
from src.infrastructure.models.workflow_stage_model import WorkflowStageModel
from src.infrastructure.models.procurement_model import ProcurementRequestModel, ProcurementMilestoneModel
from src.infrastructure.models.document_model import DocumentModel
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.activity_model import ProcurementActivityLogModel
from src.infrastructure.models.notification_model import NotificationModel
from src.infrastructure.storage.s3_service import s3_service
from src.infrastructure.ai.gemini_service import gemini_service

logger = logging.getLogger(__name__)

_AI_BG_SEMAPHORE = asyncio.Semaphore(3)
_ACTIVE_BG_TASKS: set[asyncio.Task] = set()


def _schedule_bg_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _ACTIVE_BG_TASKS.add(task)
    task.add_done_callback(_ACTIVE_BG_TASKS.discard)
    return task


async def cleanup_stale_processing_validations() -> int:
    """Mark any in-flight background validations left over from a previous server restart as failed."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(DocumentValidationLogModel).where(
                DocumentValidationLogModel.processing_status == "processing"
            )
        )
        stale_logs = res.scalars().all()
        if not stale_logs:
            return 0
        for log in stale_logs:
            log.processing_status = "failed"
            log.compliance_status = "Gagal Analisis"
            log.error_message = "Analisis terhenti karena server dimulai ulang. Silakan jalankan Evaluasi Ulang AI."
        await db.commit()
        return len(stale_logs)


def _build_validation_notification(
    validation_id: str,
    document_name: str,
    success: bool,
    overall_score: Optional[float] = None,
    compliance_status: Optional[str] = None,
    ai_fallback_notice: Optional[str] = None,
    error_message: Optional[str] = None,
    is_reeval: bool = False,
    request_id: Optional[str] = None,
) -> NotificationModel:
    action_label = "Evaluasi Ulang AI" if is_reeval else "Analisis AI"
    if success:
        score_str = f"{overall_score:.0f}/100" if overall_score is not None else "-"
        title = f"{action_label} Selesai: {document_name}"
        desc = f"Status: {compliance_status or 'Selesai'} (Skor {score_str}). Klik untuk membuka hasil pemeriksaan."
        if ai_fallback_notice:
            desc = f"{desc} | {ai_fallback_notice}"
        notif_type = "document"
    else:
        title = f"{action_label} Gagal: {document_name}"
        desc = f"Gagal memproses dokumen: {(error_message or 'Terjadi gangguan pada layanan AI')[:240]}"
        notif_type = "alert"

    return NotificationModel(
        id=f"NOTIF-{uuid.uuid4().hex[:8].upper()}",
        request_id=request_id,
        type=notif_type,
        title=title[:250],
        description=desc,
        is_read=False,
        category="Hari Ini",
        action_url=f"/dashboard/documents/result?id={validation_id}",
        created_at=datetime.now(timezone.utc),
    )


async def _run_analyze_background(
    validation_id: str,
    file_content: bytes,
    filename: str,
    mime_type: str,
    file_url: Optional[str],
    compiled_rules: List[Dict[str, Any]],
    custom_prompt: Optional[str],
    active_stage_names: List[str],
    passing_threshold: float,
    warning_threshold: float,
    strict_mandatory: bool,
    target_stage_to_clear: Optional[str],
    profile_name: Optional[str],
    profile_document_kind: Optional[str],
    actor_id: Optional[str],
    actor_name: Optional[str],
    request_id: Optional[str],
    ai_tier: str,
) -> None:
    async with _AI_BG_SEMAPHORE:
        try:
            ai_result = await gemini_service.validate_document_checklist(
                file_content=file_content,
                mime_type=mime_type,
                checklist_items=compiled_rules,
                custom_prompt=custom_prompt,
                document_name=filename,
                available_workflow_stages=active_stage_names or None,
                ai_tier=ai_tier,
                allow_long_timeout=True,
            )

            ai_meta = ai_result.get("_ai_meta") or {}
            overall_score, compliance_status, summary, checklist_evaluations = _apply_weighted_scoring(
                ai_result=ai_result,
                compiled_rules=compiled_rules,
                passing_threshold=passing_threshold,
                warning_threshold=warning_threshold,
                strict_mandatory=strict_mandatory,
            )
            recommendations = ai_result.get("recommendations", [])
            extracted_project_data = ai_result.get("extracted_project", {})
            raw_stages = extracted_project_data.get("stages", [])
            if target_stage_to_clear and compliance_status in ("Lulus Verifikasi", "Catatan Procurement"):
                for s in raw_stages:
                    if s.get("step") == target_stage_to_clear or target_stage_to_clear.lower() in s.get("step", "").lower():
                        s["auto_cleared"] = True
                        s["status"] = "Done"
                        s["notes"] = f"Auto-cleared berdasarkan standar kelayakan '{profile_name or 'Profil'}'"

            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    select(DocumentValidationLogModel).where(DocumentValidationLogModel.id == validation_id)
                )
                val_log = res.scalars().first()
                if not val_log:
                    return

                now = datetime.now(timezone.utc)
                linked_doc_id = val_log.document_id

                if request_id and not linked_doc_id:
                    req_check = await db.execute(
                        select(ProcurementRequestModel).where(ProcurementRequestModel.id == request_id)
                    )
                    existing_req = req_check.scalars().first()
                    if existing_req:
                        linked_doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
                        doc_status = (
                            "Lulus Verifikasi"
                            if compliance_status == "Lulus Verifikasi"
                            else ("Tindak Lanjut FPP" if compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
                        )
                        doc_issues = [
                            f"{e.get('item', 'Klausul')}: {e.get('explanation', 'Perlu perbaikan')}"
                            for e in checklist_evaluations
                            if e.get("status") != "Memenuhi"
                        ]
                        doc_record = DocumentModel(
                            id=linked_doc_id,
                            request_id=request_id,
                            name=filename,
                            type="Wajib",
                            document_kind=profile_document_kind or "Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                            status=doc_status,
                            upload_date=now,
                            pic_id=actor_id or "USR-ADMIN",
                            pic_name=actor_name or "Administrator",
                            issues=doc_issues,
                            next_action=recommendations[0] if recommendations else "Lanjutkan ke tahapan pengadaan.",
                            procurement_step=existing_req.current_step,
                            file_url=file_url,
                            mime_type=mime_type,
                            version_number=1,
                        )
                        db.add(doc_record)

                        act_log = ProcurementActivityLogModel(
                            id=str(uuid.uuid4()),
                            request_id=request_id,
                            user_id=actor_id or "USR-ADMIN",
                            user_name=actor_name or "Administrator",
                            action="DOCUMENT_VALIDATED",
                            previous_state=None,
                            new_state=compliance_status,
                            notes=f"Dokumen '{filename}' divalidasi AI (Skor: {overall_score:.1f}%, Status: {compliance_status}).",
                            created_at=now,
                        )
                        db.add(act_log)
                        val_log.document_id = linked_doc_id

                val_log.validation_result = ai_result
                val_log.overall_score = overall_score
                val_log.compliance_status = compliance_status
                val_log.processing_status = "completed"
                val_log.ai_tier_requested = ai_meta.get("ai_tier_requested") or ai_tier
                val_log.ai_tier_used = ai_meta.get("ai_tier_used")
                val_log.ai_model_used = ai_meta.get("ai_model_used")
                val_log.ai_fallback_notice = ai_meta.get("ai_fallback_notice")
                val_log.error_message = None

                db.add(
                    _build_validation_notification(
                        validation_id=validation_id,
                        document_name=filename,
                        success=True,
                        overall_score=overall_score,
                        compliance_status=compliance_status,
                        ai_fallback_notice=val_log.ai_fallback_notice,
                        is_reeval=False,
                        request_id=val_log.request_id,
                    )
                )
                await db.commit()
                logger.info(f"Background AI analysis completed for {validation_id} ({filename})")
        except Exception as exc:
            logger.exception(f"Background AI analysis failed for {validation_id}: {exc}")
            err_msg = str(exc)[:1000]
            try:
                async with AsyncSessionLocal() as db:
                    res = await db.execute(
                        select(DocumentValidationLogModel).where(DocumentValidationLogModel.id == validation_id)
                    )
                    val_log = res.scalars().first()
                    if val_log:
                        val_log.processing_status = "failed"
                        val_log.compliance_status = "Gagal Analisis"
                        val_log.error_message = err_msg
                        db.add(
                            _build_validation_notification(
                                validation_id=validation_id,
                                document_name=filename,
                                success=False,
                                error_message=err_msg,
                                is_reeval=False,
                            )
                        )
                        await db.commit()
            except Exception as db_exc:
                logger.error(f"Failed to persist background error state for {validation_id}: {db_exc}")


async def _run_reevaluate_background(
    validation_id: str,
    document_name: str,
    file_bytes: bytes,
    mime_type: str,
    compiled_rules: List[Dict[str, Any]],
    custom_prompt: Optional[str],
    active_stage_names: List[str],
    passing_threshold: float,
    warning_threshold: float,
    actor_id: Optional[str],
    actor_name: Optional[str],
    ai_tier: str,
) -> None:
    async with _AI_BG_SEMAPHORE:
        try:
            ai_result = await gemini_service.validate_document_checklist(
                file_content=file_bytes,
                mime_type=mime_type,
                checklist_items=compiled_rules,
                custom_prompt=custom_prompt,
                document_name=document_name,
                available_workflow_stages=active_stage_names or None,
                ai_tier=ai_tier,
                allow_long_timeout=True,
            )

            ai_meta = ai_result.get("_ai_meta") or {}
            overall_score, compliance_status, summary, checklist_evaluations = _apply_weighted_scoring(
                ai_result=ai_result,
                compiled_rules=compiled_rules,
                passing_threshold=passing_threshold,
                warning_threshold=warning_threshold,
                strict_mandatory=True,
            )

            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    select(DocumentValidationLogModel).where(DocumentValidationLogModel.id == validation_id)
                )
                val_log = res.scalars().first()
                if not val_log:
                    return

                val_log.user_prompt = custom_prompt
                val_log.checklist_snapshot = compiled_rules
                val_log.validation_result = ai_result
                val_log.overall_score = overall_score
                val_log.passing_score_threshold = passing_threshold
                val_log.compliance_status = compliance_status
                val_log.processing_status = "completed"
                val_log.ai_tier_requested = ai_meta.get("ai_tier_requested") or ai_tier
                val_log.ai_tier_used = ai_meta.get("ai_tier_used")
                val_log.ai_model_used = ai_meta.get("ai_model_used")
                val_log.ai_fallback_notice = ai_meta.get("ai_fallback_notice")
                val_log.error_message = None
                if actor_id:
                    val_log.validated_by_id = actor_id
                if actor_name:
                    val_log.validated_by_name = actor_name

                if val_log.document_id:
                    doc_res = await db.execute(
                        select(DocumentModel).where(DocumentModel.id == val_log.document_id)
                    )
                    doc = doc_res.scalars().first()
                    if doc:
                        doc.status = (
                            "Lulus Verifikasi"
                            if compliance_status == "Lulus Verifikasi"
                            else ("Tindak Lanjut FPP" if compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
                        )
                        doc.issues = [
                            f"{e.get('item', 'Klausul')}: {e.get('explanation', 'Perlu perbaikan')}"
                            for e in checklist_evaluations
                            if e.get("status") != "Memenuhi"
                        ]
                        recs = ai_result.get("recommendations") or []
                        if recs:
                            doc.next_action = recs[0]

                db.add(
                    _build_validation_notification(
                        validation_id=validation_id,
                        document_name=document_name,
                        success=True,
                        overall_score=overall_score,
                        compliance_status=compliance_status,
                        ai_fallback_notice=val_log.ai_fallback_notice,
                        is_reeval=True,
                        request_id=val_log.request_id,
                    )
                )
                await db.commit()
                logger.info(f"Background AI re-evaluation completed for {validation_id}")
        except Exception as exc:
            logger.exception(f"Background AI re-evaluation failed for {validation_id}: {exc}")
            err_msg = str(exc)[:1000]
            try:
                async with AsyncSessionLocal() as db:
                    res = await db.execute(
                        select(DocumentValidationLogModel).where(DocumentValidationLogModel.id == validation_id)
                    )
                    val_log = res.scalars().first()
                    if val_log:
                        val_log.processing_status = "failed"
                        val_log.compliance_status = "Gagal Analisis"
                        val_log.error_message = err_msg
                        db.add(
                            _build_validation_notification(
                                validation_id=validation_id,
                                document_name=document_name,
                                success=False,
                                error_message=err_msg,
                                is_reeval=True,
                            )
                        )
                        await db.commit()
            except Exception as db_exc:
                logger.error(f"Failed to persist background re-eval error for {validation_id}: {db_exc}")
from src.domain.procurement_workflow import METHOD_STEPS, STEP_TO_STAGE, steps_for_method, DEFAULT_METHOD
from src.domain.exceptions import NotFoundException, ValidationException
from src.application.dtos.validation_dto import (
    ChecklistItemResultDto,
    ChecklistRuleItemDto,
    CreateValidationProfileDto,
    UpdateValidationProfileDto,
    ValidationProfileResponseDto,
    ExtractedStageDto,
    ExtractedProjectDto,
    DocumentValidationResponseDto,
    PublishValidationToTrackerRequestDto,
    UpdateValidationDecisionDto,
    ReevaluateValidationDto,
    ValidationLogListItemDto,
    WorkflowStageCreateDto,
    WorkflowStageUpdateDto,
    WorkflowStageReorderDto,
    WorkflowStageResponseDto,
)


def _compile_weighted_rules(
    profile_rules: List[Dict[str, Any]],
    adhoc_items: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Build authoritative list of weighted checklist rules.
    If adhoc_items is supplied (e.g. from FE ChecklistEditor), preserve exact user-configured items,
    weights, mandatory flags, guidance, and template/custom origin tags.
    Otherwise fall back to profile_rules or defaults.
    """
    compiled: List[Dict[str, Any]] = []

    if adhoc_items:
        for itm in adhoc_items:
            if isinstance(itm, dict):
                text = str(itm.get("item", "")).strip()
                if not text:
                    continue
                is_mand = bool(itm.get("is_mandatory", False))
                try:
                    weight_val = float(itm.get("weight", 0))
                except (TypeError, ValueError):
                    weight_val = 0.0
                compiled.append({
                    "category": str(itm.get("category") or "Umum").strip(),
                    "item": text,
                    "guidance": itm.get("guidance") or None,
                    "is_mandatory": is_mand,
                    "weight": max(0.0, weight_val),
                    "severity_on_failure": itm.get("severity_on_failure") or ("ERROR" if is_mand else "WARNING"),
                    "source": itm.get("source") or "custom",
                })
            elif isinstance(itm, str) and itm.strip():
                compiled.append({
                    "category": "Umum",
                    "item": itm.strip(),
                    "guidance": None,
                    "is_mandatory": False,
                    "weight": 0.0,
                    "severity_on_failure": "WARNING",
                    "source": "custom",
                })
    elif profile_rules:
        for r in profile_rules:
            text = str(r.get("item", "")).strip()
            if not text:
                continue
            is_mand = bool(r.get("is_mandatory", True))
            try:
                weight_val = float(r.get("weight", 0))
            except (TypeError, ValueError):
                weight_val = 0.0
            compiled.append({
                "category": str(r.get("category") or "Umum").strip(),
                "item": text,
                "guidance": r.get("guidance") or None,
                "is_mandatory": is_mand,
                "weight": max(0.0, weight_val),
                "severity_on_failure": r.get("severity_on_failure") or ("ERROR" if is_mand else "WARNING"),
                "source": "template",
            })

    if not compiled:
        defaults = [
            "Nama pekerjaan dan lingkup kebutuhan",
            "Spesifikasi teknis / Kerangka Acuan Kerja",
            "Perkiraan nilai anggaran / HPS",
            "Jadwal pelaksanaan & jangka waktu pemenuhan",
            "Ketentuan pembayaran & jaminan",
        ]
        equal_w = round(100.0 / len(defaults), 2)
        for text in defaults:
            compiled.append({
                "category": "Umum",
                "item": text,
                "guidance": None,
                "is_mandatory": False,
                "weight": equal_w,
                "severity_on_failure": "WARNING",
                "source": "custom",
            })

    # If all weights are 0, default to equal distribution (100 / N)
    if sum(r["weight"] for r in compiled) <= 0:
        equal_w = round(100.0 / len(compiled), 2)
        for idx, r in enumerate(compiled):
            r["weight"] = round(100.0 - equal_w * (len(compiled) - 1), 2) if idx == len(compiled) - 1 else equal_w

    return compiled


def _apply_weighted_scoring(
    ai_result: Dict[str, Any],
    compiled_rules: List[Dict[str, Any]],
    passing_threshold: float,
    warning_threshold: float,
    strict_mandatory: bool,
) -> tuple[float, str, str, List[Dict[str, Any]]]:
    """
    Deterministically normalize criterion weights to 100%, compute per-item earned scores
    from AI's fulfillment_ratio, and derive overall_score & compliance_status.
    """
    raw_evals = list(ai_result.get("checklist_evaluations") or [])
    summary = str(ai_result.get("summary") or "Pemeriksaan dokumen selesai.")

    total_raw_weight = sum(max(0.0, float(r.get("weight", 0.0))) for r in compiled_rules)
    n_rules = max(len(compiled_rules), 1)
    rule_by_lower = {r["item"].strip().lower(): r for r in compiled_rules}

    # Precompute normalized weights summing to 100%
    norm_weights: Dict[str, float] = {}
    for r in compiled_rules:
        raw_w = max(0.0, float(r.get("weight", 0.0)))
        norm_w = (raw_w / total_raw_weight) * 100.0 if total_raw_weight > 0 else (100.0 / n_rules)
        norm_weights[r["item"].strip().lower()] = norm_w

    enriched_evals: List[Dict[str, Any]] = []
    failed_mandatory_items: List[str] = []
    total_earned = 0.0

    for idx, e in enumerate(raw_evals):
        item_name = str(e.get("item", "")).strip()
        key = item_name.lower()
        matched_rule = rule_by_lower.get(key)
        if not matched_rule and idx < len(compiled_rules):
            matched_rule = compiled_rules[idx]
            key = matched_rule["item"].strip().lower()

        raw_w = float(matched_rule.get("weight", 0.0)) if matched_rule else round(100.0 / max(len(raw_evals), 1), 2)
        norm_w = norm_weights.get(key, 100.0 / max(len(raw_evals), 1))
        is_mand = bool(matched_rule.get("is_mandatory", False)) if matched_rule else bool(e.get("is_mandatory", False))
        source = matched_rule.get("source") if matched_rule else e.get("source")

        status = str(e.get("status") or "Perlu Perhatian")
        raw_ratio = e.get("fulfillment_ratio")
        if raw_ratio is not None:
            try:
                ratio = max(0.0, min(1.0, float(raw_ratio)))
            except (TypeError, ValueError):
                ratio = 1.0 if status == "Memenuhi" else (0.5 if status == "Perlu Perhatian" else 0.0)
        else:
            ratio = 1.0 if status == "Memenuhi" else (0.5 if status == "Perlu Perhatian" else 0.0)

        earned = round(norm_w * ratio, 2)
        total_earned += earned

        severity = e.get("severity") or (
            "SUCCESS" if status == "Memenuhi" else ("ERROR" if status == "Tidak Memenuhi" else "WARNING")
        )
        if is_mand and status == "Tidak Memenuhi":
            failed_mandatory_items.append(item_name or (matched_rule["item"] if matched_rule else f"Kriteria #{idx + 1}"))
            severity = "ERROR"

        enriched_evals.append({
            "item": item_name or (matched_rule["item"] if matched_rule else f"Kriteria #{idx + 1}"),
            "status": status,
            "evidence_quote": e.get("evidence_quote"),
            "explanation": e.get("explanation"),
            "comparison_detail": e.get("comparison_detail"),
            "severity": severity,
            "is_mandatory": is_mand,
            "weight": round(raw_w, 2),
            "normalized_weight": round(norm_w, 2),
            "fulfillment_ratio": round(ratio, 2),
            "earned_score": earned,
            "source": source,
        })

    overall_score = round(min(100.0, max(0.0, total_earned)), 1) if enriched_evals else float(ai_result.get("overall_score", 0.0))

    if failed_mandatory_items and strict_mandatory:
        compliance_status = "Perlu Perbaikan"
        if "Gagal memenuhi butir wajib" not in summary:
            summary += f" [PERINGATAN: Gagal memenuhi butir wajib (Mandatory): {', '.join(failed_mandatory_items)}]"
    elif overall_score >= passing_threshold:
        compliance_status = "Lulus Verifikasi"
    elif overall_score >= warning_threshold:
        compliance_status = "Catatan Procurement"
    else:
        compliance_status = "Perlu Perbaikan"

    ai_result["overall_score"] = overall_score
    ai_result["compliance_status"] = compliance_status
    ai_result["summary"] = summary
    ai_result["checklist_evaluations"] = enriched_evals
    return overall_score, compliance_status, summary, enriched_evals


def _parse_snapshot_rules(snapshot: Any) -> List[ChecklistRuleItemDto]:
    """Safely convert stored checklist_snapshot (list of dicts or strings) to typed ChecklistRuleItemDto list."""
    rules: List[ChecklistRuleItemDto] = []
    if not isinstance(snapshot, list):
        return rules
    n = max(len(snapshot), 1)
    default_w = round(100.0 / n, 2)
    for item in snapshot:
        if isinstance(item, dict):
            rules.append(ChecklistRuleItemDto(
                category=item.get("category", "Umum"),
                item=str(item.get("item", "")),
                guidance=item.get("guidance"),
                is_mandatory=bool(item.get("is_mandatory", False)),
                weight=float(item.get("weight", default_w)),
                severity_on_failure=item.get("severity_on_failure", "WARNING"),
                source=item.get("source"),
            ))
        elif isinstance(item, str) and item.strip():
            rules.append(ChecklistRuleItemDto(
                category="Umum",
                item=item.strip(),
                is_mandatory=False,
                weight=default_w,
                severity_on_failure="WARNING",
            ))
    return rules


class ManageValidationProfilesUseCase:
    """Use case for CRUD operations on reusable validation profiles / standards."""
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_dto(model: ValidationProfileModel) -> ValidationProfileResponseDto:
        rules = [
            ChecklistRuleItemDto(
                category=r.get("category", "Umum"),
                item=r.get("item", ""),
                guidance=r.get("guidance"),
                is_mandatory=bool(r.get("is_mandatory", True)),
                weight=float(r.get("weight", 25)),
                severity_on_failure=r.get("severity_on_failure", "ERROR"),
                source="template",
            )
            for r in (model.checklist_rules or [])
        ]
        return ValidationProfileResponseDto(
            id=model.id,
            name=model.name,
            code=model.code,
            document_kind=model.document_kind,
            description=model.description,
            scope=model.scope,
            department_id=model.department_id,
            department_name=model.department_name,
            passing_score_threshold=model.passing_score_threshold,
            warning_score_threshold=model.warning_score_threshold,
            strict_mandatory_enforcement=model.strict_mandatory_enforcement,
            target_stage_to_clear=model.target_stage_to_clear,
            custom_system_prompt=model.custom_system_prompt,
            checklist_rules=rules,
            is_default=model.is_default,
            is_active=model.is_active,
            created_by_id=model.created_by_id,
            created_by_name=model.created_by_name,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def list_profiles(
        self,
        document_kind: Optional[str] = None,
        scope: Optional[str] = None,
        active_only: bool = True
    ) -> List[ValidationProfileResponseDto]:
        q = select(ValidationProfileModel)
        if active_only:
            q = q.where(ValidationProfileModel.is_active == True)
        if document_kind:
            q = q.where(ValidationProfileModel.document_kind == document_kind)
        if scope:
            q = q.where(ValidationProfileModel.scope == scope)
        q = q.order_by(desc(ValidationProfileModel.is_default), ValidationProfileModel.name)
        res = await self.session.execute(q)
        profiles = res.scalars().all()
        return [self._to_dto(p) for p in profiles]

    async def get_by_id(self, profile_id: str) -> ValidationProfileResponseDto:
        res = await self.session.execute(
            select(ValidationProfileModel).where(ValidationProfileModel.id == profile_id)
        )
        p = res.scalars().first()
        if not p:
            raise NotFoundException(f"Profil validasi '{profile_id}' tidak ditemukan")
        return self._to_dto(p)

    async def create_profile(
        self,
        dto: CreateValidationProfileDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None
    ) -> ValidationProfileResponseDto:
        now = datetime.now(timezone.utc)
        profile_id = f"VPROF-{uuid.uuid4().hex[:8].upper()}"
        code = dto.code or f"STD_{dto.name.upper().replace(' ', '_')[:24]}_{uuid.uuid4().hex[:6].upper()}"

        model = ValidationProfileModel(
            id=profile_id,
            name=dto.name,
            code=code,
            document_kind=dto.document_kind,
            description=dto.description,
            scope=dto.scope,
            department_id=dto.department_id,
            department_name=dto.department_name,
            passing_score_threshold=dto.passing_score_threshold,
            warning_score_threshold=dto.warning_score_threshold,
            strict_mandatory_enforcement=dto.strict_mandatory_enforcement,
            target_stage_to_clear=dto.target_stage_to_clear,
            custom_system_prompt=dto.custom_system_prompt,
            checklist_rules=[r.model_dump() for r in dto.checklist_rules],
            is_default=dto.is_default,
            is_active=True,
            created_by_id=actor_id,
            created_by_name=actor_name,
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return self._to_dto(model)

    async def update_profile(
        self,
        profile_id: str,
        dto: UpdateValidationProfileDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None
    ) -> ValidationProfileResponseDto:
        res = await self.session.execute(
            select(ValidationProfileModel).where(ValidationProfileModel.id == profile_id)
        )
        model = res.scalars().first()
        if not model:
            raise NotFoundException(f"Profil validasi '{profile_id}' tidak ditemukan")

        update_data = dto.model_dump(exclude_unset=True)
        if "checklist_rules" in update_data and update_data["checklist_rules"] is not None:
            update_data["checklist_rules"] = [
                r.model_dump() if hasattr(r, "model_dump") else r
                for r in update_data["checklist_rules"]
            ]

        for k, v in update_data.items():
            setattr(model, k, v)

        model.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(model)
        return self._to_dto(model)

    async def delete_profile(self, profile_id: str) -> bool:
        res = await self.session.execute(
            select(ValidationProfileModel).where(ValidationProfileModel.id == profile_id)
        )
        model = res.scalars().first()
        if not model:
            raise NotFoundException(f"Profil validasi '{profile_id}' tidak ditemukan")
        model.is_active = False
        model.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True


class AnalyzeDocumentChecklistUseCase:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute(
        self,
        file_content: bytes,
        filename: str,
        mime_type: str,
        profile_id: Optional[str] = None,
        checklist_items: Optional[List[Any]] = None,
        passing_score_threshold: Optional[float] = None,
        custom_prompt: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        request_id: Optional[str] = None,
        ai_tier: str = "cekatan",
        async_mode: bool = True,
    ) -> DocumentValidationResponseDto:
        norm_tier = gemini_service.normalize_tier(ai_tier)

        # 1. Resolve Profile (Template) if provided
        profile: Optional[ValidationProfileModel] = None
        profile_rules: List[Dict[str, Any]] = []
        target_stage_to_clear = None
        strict_mandatory = True
        passing_threshold = passing_score_threshold or 80.0
        warning_threshold = 60.0

        if profile_id:
            res = await self.session.execute(
                select(ValidationProfileModel).where(ValidationProfileModel.id == profile_id)
            )
            profile = res.scalars().first()
            if profile:
                profile_rules = profile.checklist_rules or []
                passing_threshold = passing_score_threshold or profile.passing_score_threshold or 80.0
                warning_threshold = profile.warning_score_threshold or 60.0
                strict_mandatory = profile.strict_mandatory_enforcement
                target_stage_to_clear = profile.target_stage_to_clear
                if profile.custom_system_prompt:
                    custom_prompt = f"{profile.custom_system_prompt}\n{custom_prompt or ''}".strip()

        # 2. Compile weighted checklist rules (preserving weights, guidance, mandatory, source)
        compiled_rules = _compile_weighted_rules(profile_rules, checklist_items)

        # Fetch active workflow stages from DB so AI can align extracted stages with org workflow
        stages_res = await self.session.execute(
            select(WorkflowStageModel)
            .where(WorkflowStageModel.is_active == True)
            .order_by(WorkflowStageModel.procurement_method, WorkflowStageModel.order_index)
        )
        active_stage_names = [s.step_name for s in stages_res.scalars().all()]

        # 3. Upload to local volume / S3 storage
        file_url = None
        object_key = f"documents/validations/{uuid.uuid4().hex[:8]}/{filename}"
        try:
            file_url = s3_service.upload_file(io.BytesIO(file_content), object_key, content_type=mime_type)
        except Exception:
            file_url = f"/uploads/{filename}"

        validation_id = f"VAL-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)

        # ── ASYNC BACKGROUND PATH (Default) ──────────────────────────────────
        if async_mode:
            clean_title = filename.rsplit(".", 1)[0].replace("_", " ").title()
            placeholder_result: Dict[str, Any] = {
                "summary": "Dokumen sedang dianalisis AI di latar belakang. Anda dapat berpindah halaman dan akan menerima notifikasi saat selesai.",
                "checklist_evaluations": [],
                "recommendations": [],
                "extracted_project": {
                    "title": clean_title,
                    "estimated_amount": 0.0,
                    "suggested_method": DEFAULT_METHOD,
                    "department_name": "Procurement & General Support",
                    "stages": [],
                },
            }
            log_model = DocumentValidationLogModel(
                id=validation_id,
                request_id=request_id,
                document_id=None,
                profile_id=profile.id if profile else None,
                profile_name=profile.name if profile else None,
                document_name=filename,
                document_file_url=file_url,
                mime_type=mime_type,
                user_prompt=custom_prompt,
                checklist_snapshot=compiled_rules,
                validation_result=placeholder_result,
                overall_score=0.0,
                passing_score_threshold=passing_threshold,
                compliance_status="Sedang Dianalisis",
                processing_status="processing",
                ai_tier_requested=norm_tier,
                validated_by_id=actor_id or "USR-ADMIN",
                validated_by_name=actor_name or "Administrator",
                created_at=now,
            )
            self.session.add(log_model)
            await self.session.commit()
            await self.session.refresh(log_model)

            _schedule_bg_task(
                _run_analyze_background(
                    validation_id=validation_id,
                    file_content=file_content,
                    filename=filename,
                    mime_type=mime_type,
                    file_url=file_url,
                    compiled_rules=compiled_rules,
                    custom_prompt=custom_prompt,
                    active_stage_names=active_stage_names,
                    passing_threshold=passing_threshold,
                    warning_threshold=warning_threshold,
                    strict_mandatory=strict_mandatory,
                    target_stage_to_clear=target_stage_to_clear,
                    profile_name=profile.name if profile else None,
                    profile_document_kind=profile.document_kind if profile else None,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    request_id=request_id,
                    ai_tier=norm_tier,
                )
            )

            return DocumentValidationResponseDto(
                id=log_model.id,
                document_name=log_model.document_name,
                document_file_url=log_model.document_file_url,
                mime_type=log_model.mime_type,
                profile_id=log_model.profile_id,
                profile_name=log_model.profile_name,
                overall_score=0.0,
                passing_score_threshold=passing_threshold,
                compliance_status="Sedang Dianalisis",
                summary=placeholder_result["summary"],
                user_prompt=log_model.user_prompt,
                checklist_rules=_parse_snapshot_rules(log_model.checklist_snapshot),
                checklist_evaluations=[],
                recommendations=[],
                extracted_project=ExtractedProjectDto(
                    title=clean_title,
                    estimated_amount=0.0,
                    suggested_method=DEFAULT_METHOD,
                    department_name="Procurement & General Support",
                    stages=[],
                ),
                created_at=log_model.created_at,
                request_id=log_model.request_id,
                document_id=log_model.document_id,
                processing_status="processing",
                ai_tier_requested=norm_tier,
                ai_tier_used=None,
                ai_model_used=None,
                ai_fallback_notice=None,
                error_message=None,
            )

        # ── SYNCHRONOUS PATH ─────────────────────────────────────────────────
        ai_result = await gemini_service.validate_document_checklist(
            file_content=file_content,
            mime_type=mime_type,
            checklist_items=compiled_rules,
            custom_prompt=custom_prompt,
            document_name=filename,
            available_workflow_stages=active_stage_names or None,
            ai_tier=norm_tier,
            allow_long_timeout=False,
        )
        ai_meta = ai_result.get("_ai_meta") or {}

        # 5. Deterministic normalized weighted scoring & mandatory enforcement
        overall_score, compliance_status, summary, checklist_evaluations = _apply_weighted_scoring(
            ai_result=ai_result,
            compiled_rules=compiled_rules,
            passing_threshold=passing_threshold,
            warning_threshold=warning_threshold,
            strict_mandatory=strict_mandatory,
        )
        recommendations = ai_result.get("recommendations", [])
        extracted_project_data = ai_result.get("extracted_project", {})

        # 6. Apply target_stage_to_clear if profile specifies
        raw_stages = extracted_project_data.get("stages", [])
        if target_stage_to_clear and compliance_status in ("Lulus Verifikasi", "Catatan Procurement"):
            for s in raw_stages:
                if s.get("step") == target_stage_to_clear or target_stage_to_clear.lower() in s.get("step", "").lower():
                    s["auto_cleared"] = True
                    s["status"] = "Done"
                    s["notes"] = f"Auto-cleared berdasarkan standar kelayakan '{profile.name if profile else 'Profil'}'"

        # 7. Create immutable Validation Log record (and DocumentModel if request_id is already provided)
        linked_doc_id: Optional[str] = None

        if request_id:
            req_check = await self.session.execute(
                select(ProcurementRequestModel).where(ProcurementRequestModel.id == request_id)
            )
            existing_req = req_check.scalars().first()
            if existing_req:
                linked_doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
                doc_status = (
                    "Lulus Verifikasi"
                    if compliance_status == "Lulus Verifikasi"
                    else ("Tindak Lanjut FPP" if compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
                )
                doc_issues = [
                    f"{e.get('item', 'Klausul')}: {e.get('explanation', 'Perlu perbaikan')}"
                    for e in checklist_evaluations
                    if e.get("status") != "Memenuhi"
                ]
                doc_record = DocumentModel(
                    id=linked_doc_id,
                    request_id=request_id,
                    name=filename,
                    type="Wajib",
                    document_kind=profile.document_kind if profile else "Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                    status=doc_status,
                    upload_date=now,
                    pic_id=actor_id or "USR-ADMIN",
                    pic_name=actor_name or "Administrator",
                    issues=doc_issues,
                    next_action=recommendations[0] if recommendations else "Lanjutkan ke tahapan pengadaan.",
                    procurement_step=existing_req.current_step,
                    file_url=file_url,
                    mime_type=mime_type,
                    version_number=1,
                )
                self.session.add(doc_record)

                act_log = ProcurementActivityLogModel(
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=actor_id or "USR-ADMIN",
                    user_name=actor_name or "Administrator",
                    action="DOCUMENT_VALIDATED",
                    previous_state=None,
                    new_state=compliance_status,
                    notes=f"Dokumen '{filename}' divalidasi AI (Skor: {overall_score:.1f}%, Status: {compliance_status}).",
                    created_at=now,
                )
                self.session.add(act_log)

        log_model = DocumentValidationLogModel(
            id=validation_id,
            request_id=request_id,
            document_id=linked_doc_id,
            profile_id=profile.id if profile else None,
            profile_name=profile.name if profile else None,
            document_name=filename,
            document_file_url=file_url,
            mime_type=mime_type,
            user_prompt=custom_prompt,
            checklist_snapshot=compiled_rules,
            validation_result=ai_result,
            overall_score=overall_score,
            passing_score_threshold=passing_threshold,
            compliance_status=compliance_status,
            processing_status="completed",
            ai_tier_requested=ai_meta.get("ai_tier_requested") or norm_tier,
            ai_tier_used=ai_meta.get("ai_tier_used"),
            ai_model_used=ai_meta.get("ai_model_used"),
            ai_fallback_notice=ai_meta.get("ai_fallback_notice"),
            validated_by_id=actor_id or "USR-ADMIN",
            validated_by_name=actor_name or "Administrator",
            created_at=now,
        )

        self.session.add(log_model)
        await self.session.commit()
        await self.session.refresh(log_model)

        # 8. Construct typed response DTO
        eval_dtos = [
            ChecklistItemResultDto(
                item=e.get("item", ""),
                status=e.get("status", "Perlu Perhatian"),
                evidence_quote=e.get("evidence_quote"),
                explanation=e.get("explanation"),
                comparison_detail=e.get("comparison_detail"),
                severity=e.get("severity", "WARNING"),
                is_mandatory=bool(e.get("is_mandatory", False)),
                weight=float(e.get("weight", 0.0)),
                normalized_weight=float(e.get("normalized_weight", 0.0)),
                fulfillment_ratio=float(e.get("fulfillment_ratio", 1.0)),
                earned_score=float(e.get("earned_score", 0.0)),
                source=e.get("source"),
            )
            for e in checklist_evaluations
        ]

        stage_dtos = [
            ExtractedStageDto(
                step=s.get("step", ""),
                status=s.get("status", "Pending"),
                auto_cleared=bool(s.get("auto_cleared", False)),
                notes=s.get("notes"),
            )
            for s in raw_stages
        ]

        project_dto = ExtractedProjectDto(
            title=extracted_project_data.get("title", filename.rsplit(".", 1)[0].replace("_", " ").title()),
            estimated_amount=float(extracted_project_data.get("estimated_amount", 0.0)),
            suggested_method=extracted_project_data.get("suggested_method", DEFAULT_METHOD),
            department_name=extracted_project_data.get("department_name", "Procurement & General Support"),
            stages=stage_dtos,
        )

        signed_file_url = (
            s3_service.generate_presigned_url(
                log_model.document_file_url,
                expiration=1800,
                inline_filename=log_model.document_name,
            )
            if log_model.document_file_url
            else None
        )

        return DocumentValidationResponseDto(
            id=log_model.id,
            document_name=log_model.document_name,
            document_file_url=log_model.document_file_url,
            file_url_signed=signed_file_url,
            mime_type=log_model.mime_type,
            profile_id=log_model.profile_id,
            profile_name=log_model.profile_name,
            overall_score=log_model.overall_score,
            passing_score_threshold=passing_threshold,
            compliance_status=log_model.compliance_status,
            summary=summary,
            user_prompt=log_model.user_prompt,
            checklist_rules=_parse_snapshot_rules(log_model.checklist_snapshot),
            checklist_evaluations=eval_dtos,
            recommendations=recommendations,
            extracted_project=project_dto,
            created_at=log_model.created_at,
            request_id=log_model.request_id,
            document_id=log_model.document_id,
            processing_status=log_model.processing_status or "completed",
            ai_tier_requested=log_model.ai_tier_requested,
            ai_tier_used=log_model.ai_tier_used,
            ai_model_used=log_model.ai_model_used,
            ai_fallback_notice=log_model.ai_fallback_notice,
            error_message=log_model.error_message,
        )


class ReevaluateValidationUseCase:
    """Re-runs real Gemini AI evaluation on an already-uploaded document with adjusted weights/criteria/prompt."""
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute(
        self,
        validation_id: str,
        payload: ReevaluateValidationDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> DocumentValidationResponseDto:
        log_uc = GetValidationLogsUseCase(self.session)
        val_log = await log_uc._ensure_validation_log(validation_id)
        norm_tier = gemini_service.normalize_tier(payload.ai_tier)
        use_async = True if payload.async_mode is None else bool(payload.async_mode)

        # Build updated rules from payload or existing snapshot
        if payload.checklist_rules:
            raw_items = [r.model_dump() for r in payload.checklist_rules]
            compiled_rules = _compile_weighted_rules([], raw_items)
        else:
            existing_rules = [r.model_dump() for r in _parse_snapshot_rules(val_log.checklist_snapshot)]
            compiled_rules = _compile_weighted_rules([], existing_rules)

        passing_threshold = (
            payload.passing_score_threshold
            if payload.passing_score_threshold is not None
            else (val_log.passing_score_threshold or 80.0)
        )
        warning_threshold = max(50.0, passing_threshold - 20.0)
        custom_prompt = payload.custom_prompt if payload.custom_prompt is not None else val_log.user_prompt

        # Load active workflow stages for reference
        stages_res = await self.session.execute(
            select(WorkflowStageModel)
            .where(WorkflowStageModel.is_active == True)
            .order_by(WorkflowStageModel.procurement_method, WorkflowStageModel.order_index)
        )
        active_stage_names = [s.step_name for s in stages_res.scalars().all()]

        # Read original file bytes from storage (or fallback to metadata text if seeded document)
        file_bytes = s3_service.read_file_bytes(val_log.document_file_url)
        mime_type = val_log.mime_type or "application/pdf"
        if not file_bytes:
            prev_summary = (val_log.validation_result or {}).get("summary", "")
            fallback_context = (
                f"Dokumen: {val_log.document_name}\n"
                f"Profil Standar: {val_log.profile_name or '-'}\n"
                f"Ringkasan Sebelumnya: {prev_summary}\n"
            )
            file_bytes = fallback_context.encode("utf-8")
            mime_type = "text/plain"

        if use_async:
            val_log.user_prompt = custom_prompt
            val_log.checklist_snapshot = compiled_rules
            val_log.passing_score_threshold = passing_threshold
            val_log.processing_status = "processing"
            val_log.compliance_status = "Sedang Dianalisis"
            val_log.ai_tier_requested = norm_tier
            val_log.ai_tier_used = None
            val_log.ai_model_used = None
            val_log.ai_fallback_notice = None
            val_log.error_message = None
            await self.session.commit()
            await self.session.refresh(val_log)

            _schedule_bg_task(
                _run_reevaluate_background(
                    validation_id=val_log.id,
                    document_name=val_log.document_name,
                    file_bytes=file_bytes,
                    mime_type=mime_type,
                    compiled_rules=compiled_rules,
                    custom_prompt=custom_prompt,
                    active_stage_names=active_stage_names,
                    passing_threshold=passing_threshold,
                    warning_threshold=warning_threshold,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    ai_tier=norm_tier,
                )
            )
            return await log_uc.get_by_id(val_log.id)

        ai_result = await gemini_service.validate_document_checklist(
            file_content=file_bytes,
            mime_type=mime_type,
            checklist_items=compiled_rules,
            custom_prompt=custom_prompt,
            document_name=val_log.document_name,
            available_workflow_stages=active_stage_names or None,
            ai_tier=norm_tier,
            allow_long_timeout=False,
        )
        ai_meta = ai_result.get("_ai_meta") or {}

        overall_score, compliance_status, summary, checklist_evaluations = _apply_weighted_scoring(
            ai_result=ai_result,
            compiled_rules=compiled_rules,
            passing_threshold=passing_threshold,
            warning_threshold=warning_threshold,
            strict_mandatory=True,
        )

        val_log.user_prompt = custom_prompt
        val_log.checklist_snapshot = compiled_rules
        val_log.validation_result = ai_result
        val_log.overall_score = overall_score
        val_log.passing_score_threshold = passing_threshold
        val_log.compliance_status = compliance_status
        val_log.processing_status = "completed"
        val_log.ai_tier_requested = ai_meta.get("ai_tier_requested") or norm_tier
        val_log.ai_tier_used = ai_meta.get("ai_tier_used")
        val_log.ai_model_used = ai_meta.get("ai_model_used")
        val_log.ai_fallback_notice = ai_meta.get("ai_fallback_notice")
        val_log.error_message = None
        if actor_id:
            val_log.validated_by_id = actor_id
        if actor_name:
            val_log.validated_by_name = actor_name

        # Sync linked document status & issues if published
        if val_log.document_id:
            doc_res = await self.session.execute(
                select(DocumentModel).where(DocumentModel.id == val_log.document_id)
            )
            doc = doc_res.scalars().first()
            if doc:
                doc.status = (
                    "Lulus Verifikasi"
                    if compliance_status == "Lulus Verifikasi"
                    else ("Tindak Lanjut FPP" if compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
                )
                doc.issues = [
                    f"{e.get('item', 'Klausul')}: {e.get('explanation', 'Perlu perbaikan')}"
                    for e in checklist_evaluations
                    if e.get("status") != "Memenuhi"
                ]
                recs = ai_result.get("recommendations") or []
                if recs:
                    doc.next_action = recs[0]

        await self.session.commit()
        await self.session.refresh(val_log)
        return await log_uc.get_by_id(val_log.id)


class PublishValidationToTrackerUseCase:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute(
        self,
        payload: PublishValidationToTrackerRequestDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 1. Fetch Validation Log (by id or document_id)
        result = await self.session.execute(
            select(DocumentValidationLogModel).where(
                or_(
                    DocumentValidationLogModel.id == payload.validation_log_id,
                    DocumentValidationLogModel.document_id == payload.validation_log_id,
                )
            )
        )
        val_log = result.scalars().first()
        if not val_log:
            raise NotFoundException(f"Log validasi '{payload.validation_log_id}' tidak ditemukan")

        ai_project = (val_log.validation_result or {}).get("extracted_project", {})
        pic_id = payload.pic_id or actor_id or val_log.validated_by_id or "USR-ADMIN"
        pic_name = payload.pic_name or actor_name or val_log.validated_by_name or "Administrator"
        now = datetime.now(timezone.utc)

        # Build document issues from non-passing checklist items
        issues = []
        for eval_item in (val_log.validation_result or {}).get("checklist_evaluations", []):
            if eval_item.get("status") != "Memenuhi":
                item_name = eval_item.get("item", "Klausul")
                expl = eval_item.get("explanation", "Perlu perbaikan")
                issues.append(f"{item_name}: {expl}")

        doc_status = (
            "Lulus Verifikasi"
            if val_log.compliance_status == "Lulus Verifikasi"
            else ("Tindak Lanjut FPP" if val_log.compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
        )

        raw_stages = []
        if payload.stages:
            raw_stages = [s.model_dump() for s in payload.stages]
        elif ai_project.get("stages"):
            raw_stages = ai_project.get("stages")

        # ── MODE A: LINK TO EXISTING PROCUREMENT REQUEST ──
        if payload.target_request_id:
            req_res = await self.session.execute(
                select(ProcurementRequestModel).where(ProcurementRequestModel.id == payload.target_request_id)
            )
            existing_req = req_res.scalars().first()
            if not existing_req:
                raise NotFoundException(f"Pekerjaan '{payload.target_request_id}' tidak ditemukan")

            doc_id = val_log.document_id
            if doc_id:
                doc_res = await self.session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
                existing_doc = doc_res.scalars().first()
                if existing_doc:
                    existing_doc.request_id = existing_req.id
                    existing_doc.status = doc_status
                    existing_doc.issues = issues
            else:
                doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
                doc_record = DocumentModel(
                    id=doc_id,
                    request_id=existing_req.id,
                    name=val_log.document_name,
                    type="Wajib",
                    document_kind=val_log.profile_name or "Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                    status=doc_status,
                    upload_date=now,
                    pic_id=pic_id,
                    pic_name=pic_name,
                    issues=issues,
                    next_action=(
                        (val_log.validation_result or {}).get("recommendations", ["Lanjutkan ke tahapan tender."])[0]
                        if (val_log.validation_result or {}).get("recommendations")
                        else "Lanjutkan ke tahapan tender."
                    ),
                    procurement_step=existing_req.current_step,
                    file_url=val_log.document_file_url,
                    mime_type=val_log.mime_type,
                    version_number=1,
                )
                self.session.add(doc_record)

            # Auto-clear matching milestones on the existing request
            ms_res = await self.session.execute(
                select(ProcurementMilestoneModel).where(ProcurementMilestoneModel.request_id == existing_req.id)
            )
            existing_milestones = ms_res.scalars().all()
            auto_cleared_count = 0
            for s in raw_stages:
                if s.get("auto_cleared") or s.get("status") == "Done":
                    step_name = (s.get("step") or "").lower()
                    for ms in existing_milestones:
                        if ms.step and (ms.step.lower() == step_name or step_name in ms.step.lower()):
                            ms.status = "Completed"
                            ms.date = now
                            ms.notes = s.get("notes") or f"Diselesaikan otomatis melalui validasi dokumen '{val_log.document_name}'"
                            auto_cleared_count += 1

            val_log.request_id = existing_req.id
            val_log.document_id = doc_id

            activity_log = ProcurementActivityLogModel(
                id=str(uuid.uuid4()),
                request_id=existing_req.id,
                user_id=pic_id,
                user_name=pic_name,
                action="DOCUMENT_LINKED",
                previous_state=existing_req.current_step,
                new_state=existing_req.current_step,
                notes=(
                    f"Dokumen '{val_log.document_name}' ditautkan ke pekerjaan "
                    f"(Skor: {val_log.overall_score:.0f}%, Status: {val_log.compliance_status})."
                ),
                created_at=now,
            )
            self.session.add(activity_log)
            await self.session.commit()

            return {
                "success": True,
                "message": f"Dokumen berhasil ditautkan ke pekerjaan '{existing_req.title}'",
                "request_id": existing_req.id,
                "title": existing_req.title,
                "current_step": existing_req.current_step,
                "stage": existing_req.stage,
                "document_id": doc_id,
                "validation_log_id": val_log.id,
                "auto_cleared_stages_count": auto_cleared_count,
            }

        # ── MODE B: CREATE NEW PROCUREMENT REQUEST ──
        doc_clean_name = val_log.document_name.rsplit(".", 1)[0].replace("_", " ").title()
        project_title = payload.title or ai_project.get("title") or f"Pengadaan: {doc_clean_name}"
        amount = payload.amount if payload.amount is not None else float(ai_project.get("estimated_amount", 0.0))
        method = payload.procurement_method or ai_project.get("suggested_method", DEFAULT_METHOD)
        department_id = payload.department_id or "DEPT-PROC"
        department_name = payload.department_name or ai_project.get("department_name", "Procurement & General Support")
        fpp_id = payload.fpp_id or "FPP-ENG"
        fpp_name = payload.fpp_name or "Fungsi Pemohon Pengadaan"

        if not raw_stages:
            default_steps = steps_for_method(method)
            for idx, stp in enumerate(default_steps):
                raw_stages.append({
                    "step": stp,
                    "status": "In Progress" if idx == 0 else "Pending",
                    "auto_cleared": False,
                    "notes": None,
                })

        has_in_progress = any(s.get("status") == "In Progress" for s in raw_stages)
        if not has_in_progress:
            first_pending = next((s for s in raw_stages if s.get("status") == "Pending"), None)
            if first_pending:
                first_pending["status"] = "In Progress"
            elif raw_stages:
                raw_stages[0]["status"] = "In Progress"

        current_stage_step = next(
            (s.get("step") for s in raw_stages if s.get("status") == "In Progress"),
            raw_stages[0]["step"] if raw_stages else "Penyusunan RKS / Spesifikasi Teknis"
        )
        current_operational_stage = STEP_TO_STAGE.get(current_stage_step, "Sourcing")

        new_request_id = f"REQ-{datetime.now().year}-{uuid.uuid4().hex[:5].upper()}"

        proc_request = ProcurementRequestModel(
            id=new_request_id,
            title=project_title,
            pic_id=pic_id,
            pic_name=pic_name,
            fpp_id=fpp_id,
            fpp_name=fpp_name,
            amount=amount,
            stage=current_operational_stage,
            operational_status="On Going",
            current_step=current_stage_step,
            department_id=department_id,
            department_name=department_name,
            procurement_method=method,
            is_urgent=False,
            stage_started_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(proc_request)

        for s in raw_stages:
            ms_id = f"MS-{uuid.uuid4().hex[:8].upper()}"
            ms_status = s.get("status", "Pending")
            is_cleared = bool(s.get("auto_cleared", False))
            ms_date = now if (ms_status == "Done" or is_cleared) else None

            milestone = ProcurementMilestoneModel(
                id=ms_id,
                request_id=new_request_id,
                step=s.get("step"),
                status=ms_status,
                date=ms_date,
                pic_id=pic_id if ms_date else None,
                pic_name=pic_name if ms_date else None,
                notes=s.get("notes"),
            )
            self.session.add(milestone)

        doc_id = val_log.document_id or f"DOC-{uuid.uuid4().hex[:8].upper()}"
        if val_log.document_id:
            doc_res = await self.session.execute(select(DocumentModel).where(DocumentModel.id == val_log.document_id))
            existing_doc = doc_res.scalars().first()
            if existing_doc:
                existing_doc.request_id = new_request_id
                existing_doc.status = doc_status
        else:
            doc_record = DocumentModel(
                id=doc_id,
                request_id=new_request_id,
                name=val_log.document_name,
                type="Wajib",
                document_kind=val_log.profile_name or "Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                status=doc_status,
                upload_date=now,
                pic_id=pic_id,
                pic_name=pic_name,
                issues=issues,
                next_action=(
                    (val_log.validation_result or {}).get("recommendations", ["Lanjutkan ke tahapan tender."])[0]
                    if (val_log.validation_result or {}).get("recommendations")
                    else "Lanjutkan ke tahapan tender."
                ),
                procurement_step=current_stage_step,
                file_url=val_log.document_file_url,
                mime_type=val_log.mime_type,
                version_number=1,
            )
            self.session.add(doc_record)

        # Look up configured default_sla_days for current_stage_step from WorkflowStageModel
        stg_sla_res = await self.session.execute(
            select(WorkflowStageModel.default_sla_days).where(
                WorkflowStageModel.step_name == current_stage_step,
                WorkflowStageModel.is_active == True,
            ).limit(1)
        )
        configured_sla_days = stg_sla_res.scalar() or 5

        deadline_id = f"DLD-{uuid.uuid4().hex[:8].upper()}"
        deadline = DeadlineModel(
            id=deadline_id,
            request_id=new_request_id,
            task_name=f"Pelaksanaan: {current_stage_step}",
            milestone=current_stage_step,
            pic_id=pic_id,
            pic_name=pic_name,
            department_id=department_id,
            department_name=department_name,
            start_date=now,
            target_date=now + timedelta(days=max(1, int(configured_sla_days))),
            status="On Track",
            urgency_level="Medium",
            next_action=f"Selesaikan tahapan '{current_stage_step}' sesuai target SLA ({configured_sla_days} hari).",
            created_at=now,
        )
        self.session.add(deadline)

        activity_id = str(uuid.uuid4())
        auto_cleared_count = sum(1 for s in raw_stages if s.get("auto_cleared"))
        activity_log = ProcurementActivityLogModel(
            id=activity_id,
            request_id=new_request_id,
            user_id=pic_id,
            user_name=pic_name,
            action="CREATE",
            previous_state=None,
            new_state=current_operational_stage,
            notes=(
                f"Pekerjaan diterbitkan otomatis dari validasi AI dokumen '{val_log.document_name}' "
                f"(Skor: {val_log.overall_score:.0f}%, Status: {val_log.compliance_status}). "
                f"{auto_cleared_count} tahapan awal berhasil di-auto-clear."
            ),
            created_at=now,
        )
        self.session.add(activity_log)

        val_log.request_id = new_request_id
        val_log.document_id = doc_id

        await self.session.commit()
        await self.session.refresh(proc_request)

        return {
            "success": True,
            "message": f"Pekerjaan '{project_title}' berhasil diterbitkan ke Tracker",
            "request_id": new_request_id,
            "title": project_title,
            "current_step": current_stage_step,
            "stage": current_operational_stage,
            "document_id": doc_id,
            "validation_log_id": val_log.id,
            "auto_cleared_stages_count": auto_cleared_count,
        }


class GetValidationLogsUseCase:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_request_id(self, request_id: str) -> List[ValidationLogListItemDto]:
        query = (
            select(DocumentValidationLogModel)
            .where(DocumentValidationLogModel.request_id == request_id)
            .order_by(desc(DocumentValidationLogModel.created_at))
        )
        result = await self.session.execute(query)
        logs = result.scalars().all()

        items = []
        for l in logs:
            checklist = l.checklist_snapshot or []
            evals = l.validation_result.get("checklist_evaluations", []) if l.validation_result else []
            passed = sum(1 for e in evals if e.get("status") == "Memenuhi")
            items.append(
                ValidationLogListItemDto(
                    id=l.id,
                    request_id=l.request_id,
                    document_id=l.document_id,
                    profile_id=l.profile_id,
                    profile_name=l.profile_name,
                    document_name=l.document_name,
                    document_file_url=l.document_file_url,
                    overall_score=l.overall_score,
                    passing_score_threshold=l.passing_score_threshold or 80.0,
                    compliance_status=l.compliance_status,
                    checklist_count=len(checklist),
                    passed_count=passed,
                    validated_by_name=l.validated_by_name,
                    created_at=l.created_at,
                    processing_status=l.processing_status or "completed",
                    ai_tier_requested=l.ai_tier_requested,
                    ai_tier_used=l.ai_tier_used,
                    ai_model_used=l.ai_model_used,
                    ai_fallback_notice=l.ai_fallback_notice,
                    error_message=l.error_message,
                )
            )
        return items

    async def _ensure_validation_log(self, validation_or_doc_id: str) -> DocumentValidationLogModel:
        """
        Finds a DocumentValidationLogModel by id OR document_id.
        If none exists yet but a DocumentModel with that ID exists in `documents`,
        runs real Gemini AI validation via `gemini_service.validate_document_checklist`
        and persists the resulting DocumentValidationLogModel in DB.
        """
        result = await self.session.execute(
            select(DocumentValidationLogModel)
            .where(
                or_(
                    DocumentValidationLogModel.id == validation_or_doc_id,
                    DocumentValidationLogModel.document_id == validation_or_doc_id,
                )
            )
            .order_by(desc(DocumentValidationLogModel.created_at))
        )
        l = result.scalars().first()
        if l:
            return l

        # Check if it's a DocumentModel without a validation log yet
        doc_res = await self.session.execute(
            select(DocumentModel).where(DocumentModel.id == validation_or_doc_id)
        )
        doc = doc_res.scalars().first()
        if not doc:
            raise NotFoundException(f"Log validasi atau dokumen '{validation_or_doc_id}' tidak ditemukan")

        req = None
        if doc.request_id:
            req_res = await self.session.execute(
                select(ProcurementRequestModel).where(ProcurementRequestModel.id == doc.request_id)
            )
            req = req_res.scalars().first()

        checklist_items = [
            "Kelengkapan identitas, nomor, dan tanggal dokumen pengadaan",
            "Kesesuaian ruang lingkup kebutuhan dan spesifikasi teknis pekerjaan",
            "Kepatuhan estimasi nilai anggaran / HPS dan ketentuan perpajakan",
            "Jadwal pelaksanaan dan tahapan pemenuhan pekerjaan",
        ]

        # Build context prompt for real Gemini AI analysis
        context_text = (
            f"Dokumen: {doc.name}\n"
            f"Jenis Dokumen: {doc.document_kind or doc.type}\n"
            f"Nomor Dokumen: {doc.document_number or '-'}\n"
            f"Tanggal Dokumen: {doc.document_date or '-'}\n"
            f"Tahap Pengadaan: {doc.procurement_step or '-'}\n"
            f"Status Verifikasi Tercatat: {doc.status}\n"
            f"Catatan Pemeriksaan Tercatat: {'; '.join(doc.issues or []) or 'Tidak ada catatan temuan'}\n"
            f"Tindak Lanjut: {doc.next_action or '-'}\n"
        )
        if req:
            context_text += (
                f"Pekerjaan Terkait: {req.title}\n"
                f"Nilai Anggaran Pekerjaan: Rp {req.amount:,.0f}\n"
                f"Fungsi Pemohon: {req.department_name}\n"
            )

        ai_result = await gemini_service.validate_document_checklist(
            file_content=context_text.encode("utf-8"),
            mime_type="text/plain",
            checklist_items=checklist_items,
            custom_prompt=(
                f"Analisis kelayakan dokumen '{doc.name}' berdasarkan informasi dokumen berikut:\n{context_text}"
            ),
            document_name=doc.name,
        )

        overall_score = float(ai_result.get("overall_score", 80.0))
        compliance_status = ai_result.get("compliance_status") or doc.status

        new_log = DocumentValidationLogModel(
            id=f"VAL-{uuid.uuid4().hex[:8].upper()}",
            request_id=doc.request_id,
            document_id=doc.id,
            profile_id="VPROF-KAK-TEKNIS",
            profile_name=doc.document_kind or "Standar Kelayakan Dokumen Pengadaan",
            document_name=doc.name,
            document_file_url=doc.file_url,
            mime_type=doc.mime_type or "application/pdf",
            user_prompt=None,
            checklist_snapshot=checklist_items,
            validation_result=ai_result,
            overall_score=overall_score,
            passing_score_threshold=80.0,
            compliance_status=compliance_status,
            validated_by_id=doc.pic_id,
            validated_by_name=doc.pic_name,
            created_at=doc.upload_date or datetime.now(timezone.utc),
        )
        self.session.add(new_log)
        await self.session.commit()
        await self.session.refresh(new_log)
        return new_log

    async def get_by_id(self, validation_id: str) -> DocumentValidationResponseDto:
        l = await self._ensure_validation_log(validation_id)

        res_data = l.validation_result or {}
        raw_evals = res_data.get("checklist_evaluations", [])
        n_evals = max(len(raw_evals), 1)
        fallback_w = round(100.0 / n_evals, 2)
        eval_dtos = []
        for e in raw_evals:
            w = float(e.get("weight", fallback_w))
            nw = float(e.get("normalized_weight", w))
            status = e.get("status", "Perlu Perhatian")
            ratio = float(
                e.get(
                    "fulfillment_ratio",
                    1.0 if status == "Memenuhi" else (0.5 if status == "Perlu Perhatian" else 0.0),
                )
            )
            earned = float(e.get("earned_score", round(nw * ratio, 2)))
            eval_dtos.append(
                ChecklistItemResultDto(
                    item=e.get("item", ""),
                    status=status,
                    evidence_quote=e.get("evidence_quote"),
                    explanation=e.get("explanation"),
                    comparison_detail=e.get("comparison_detail"),
                    severity=e.get("severity", "WARNING"),
                    is_mandatory=bool(e.get("is_mandatory", False)),
                    weight=w,
                    normalized_weight=nw,
                    fulfillment_ratio=ratio,
                    earned_score=earned,
                    source=e.get("source"),
                )
            )

        proj_data = res_data.get("extracted_project", {})
        stage_dtos = [
            ExtractedStageDto(
                step=s.get("step", ""),
                status=s.get("status", "Pending"),
                auto_cleared=bool(s.get("auto_cleared", False)),
                notes=s.get("notes"),
            )
            for s in proj_data.get("stages", [])
        ]

        project_dto = ExtractedProjectDto(
            title=proj_data.get("title", l.document_name),
            estimated_amount=float(proj_data.get("estimated_amount", 0.0)),
            suggested_method=proj_data.get("suggested_method", DEFAULT_METHOD),
            department_name=proj_data.get("department_name", "Procurement & General Support"),
            stages=stage_dtos,
        )

        signed_file_url = (
            s3_service.generate_presigned_url(
                l.document_file_url,
                expiration=1800,
                inline_filename=l.document_name,
            )
            if l.document_file_url
            else None
        )

        return DocumentValidationResponseDto(
            id=l.id,
            document_name=l.document_name,
            document_file_url=l.document_file_url,
            file_url_signed=signed_file_url,
            mime_type=l.mime_type,
            profile_id=l.profile_id,
            profile_name=l.profile_name,
            overall_score=l.overall_score,
            passing_score_threshold=l.passing_score_threshold or 80.0,
            compliance_status=l.compliance_status,
            summary=res_data.get("summary", ""),
            user_prompt=l.user_prompt,
            checklist_rules=_parse_snapshot_rules(l.checklist_snapshot),
            checklist_evaluations=eval_dtos,
            recommendations=res_data.get("recommendations", []),
            extracted_project=project_dto,
            created_at=l.created_at,
            request_id=l.request_id,
            document_id=l.document_id,
            processing_status=l.processing_status or "completed",
            ai_tier_requested=l.ai_tier_requested,
            ai_tier_used=l.ai_tier_used,
            ai_model_used=l.ai_model_used,
            ai_fallback_notice=l.ai_fallback_notice,
            error_message=l.error_message,
        )

    async def update_decision(
        self,
        validation_id: str,
        dto: UpdateValidationDecisionDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> DocumentValidationResponseDto:
        l = await self._ensure_validation_log(validation_id)
        l.compliance_status = dto.compliance_status
        if dto.overall_score is not None:
            l.overall_score = dto.overall_score

        res_data = dict(l.validation_result or {})
        if dto.reviewer_notes:
            res_data["summary"] = dto.reviewer_notes
        if dto.next_action:
            recs = list(res_data.get("recommendations", []))
            if recs:
                recs[0] = dto.next_action
            else:
                recs = [dto.next_action]
            res_data["recommendations"] = recs
        l.validation_result = res_data

        # Sync with linked DocumentModel if present
        if l.document_id:
            doc_res = await self.session.execute(
                select(DocumentModel).where(DocumentModel.id == l.document_id)
            )
            doc = doc_res.scalars().first()
            if doc:
                doc.status = (
                    "Lulus Verifikasi"
                    if dto.compliance_status == "Lulus Verifikasi"
                    else ("Tindak Lanjut FPP" if dto.compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
                )
                if dto.next_action:
                    doc.next_action = dto.next_action

        await self.session.commit()
        await self.session.refresh(l)
        return await self.get_by_id(l.id)


class ManageWorkflowStagesUseCase:
    """Admin CRUD & reordering for configurable procurement workflow stages."""
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _ensure_seeded(self) -> None:
        count_res = await self.session.execute(select(func.count(WorkflowStageModel.id)))
        total = count_res.scalar() or 0
        if total > 0:
            return
        now = datetime.now(timezone.utc)
        counter = 1
        for method_name, steps in METHOD_STEPS.items():
            for idx, step_name in enumerate(steps):
                self.session.add(WorkflowStageModel(
                    id=f"STG-DEFAULT-{counter:03d}",
                    procurement_method=method_name,
                    step_name=step_name,
                    stage_group=STEP_TO_STAGE.get(step_name, "Sourcing"),
                    order_index=idx,
                    default_sla_days=5,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ))
                counter += 1
        await self.session.commit()

    async def list_stages(
        self,
        procurement_method: Optional[str] = None,
        active_only: bool = True,
    ) -> List[WorkflowStageResponseDto]:
        await self._ensure_seeded()
        q = select(WorkflowStageModel)
        if active_only:
            q = q.where(WorkflowStageModel.is_active == True)
        if procurement_method:
            q = q.where(WorkflowStageModel.procurement_method == procurement_method)
        q = q.order_by(
            WorkflowStageModel.procurement_method,
            WorkflowStageModel.order_index,
            WorkflowStageModel.created_at,
        )
        res = await self.session.execute(q)
        return [WorkflowStageResponseDto.model_validate(row) for row in res.scalars().all()]

    async def create_stage(self, dto: WorkflowStageCreateDto) -> WorkflowStageResponseDto:
        await self._ensure_seeded()
        now = datetime.now(timezone.utc)
        order_idx = dto.order_index
        if order_idx is None:
            max_res = await self.session.execute(
                select(func.max(WorkflowStageModel.order_index)).where(
                    WorkflowStageModel.procurement_method == dto.procurement_method,
                    WorkflowStageModel.is_active == True,
                )
            )
            max_val = max_res.scalar()
            order_idx = 0 if max_val is None else max_val + 1

        model = WorkflowStageModel(
            id=f"STG-{uuid.uuid4().hex[:8].upper()}",
            procurement_method=dto.procurement_method.strip(),
            step_name=dto.step_name.strip(),
            stage_group=dto.stage_group.strip(),
            order_index=order_idx,
            default_sla_days=dto.default_sla_days or 5,
            description=dto.description.strip() if dto.description else None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return WorkflowStageResponseDto.model_validate(model)

    async def update_stage(self, stage_id: str, dto: WorkflowStageUpdateDto) -> WorkflowStageResponseDto:
        res = await self.session.execute(select(WorkflowStageModel).where(WorkflowStageModel.id == stage_id))
        model = res.scalars().first()
        if not model:
            raise NotFoundException(f"Tahapan '{stage_id}' tidak ditemukan")

        update_data = dto.model_dump(exclude_unset=True)
        for k, v in update_data.items():
            if isinstance(v, str):
                v = v.strip()
            setattr(model, k, v)
        model.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(model)
        return WorkflowStageResponseDto.model_validate(model)

    async def reorder_stages(self, dto: WorkflowStageReorderDto) -> List[WorkflowStageResponseDto]:
        now = datetime.now(timezone.utc)
        res = await self.session.execute(
            select(WorkflowStageModel).where(
                WorkflowStageModel.procurement_method == dto.procurement_method,
                WorkflowStageModel.is_active == True,
            )
        )
        stages_by_id = {s.id: s for s in res.scalars().all()}
        for idx, stg_id in enumerate(dto.ordered_stage_ids):
            if stg_id in stages_by_id:
                stages_by_id[stg_id].order_index = idx
                stages_by_id[stg_id].updated_at = now
        await self.session.commit()
        return await self.list_stages(procurement_method=dto.procurement_method, active_only=True)

    async def delete_stage(self, stage_id: str) -> bool:
        res = await self.session.execute(select(WorkflowStageModel).where(WorkflowStageModel.id == stage_id))
        model = res.scalars().first()
        if not model:
            raise NotFoundException(f"Tahapan '{stage_id}' tidak ditemukan")
        model.is_active = False
        model.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True


