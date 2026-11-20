import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.models.procurement_model import ProcurementRequestModel
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.guarantee_model import GuaranteeModel
from src.infrastructure.models.document_model import DocumentModel
from src.infrastructure.models.validation_model import (
    DocumentValidationLogModel,
    ValidationProfileModel,
)
from src.infrastructure.ai.gemini_service import gemini_service
from src.application.dtos.omni_assistant_dto import (
    OmniAssistantResponseDto,
    OmniReferencedItemDto,
    OmniCommandDto,
    OmniChatHistoryTurnDto,
)

_ALLOWED_COMMAND_TYPES = {
    "NAVIGATE",
    "COMPLETE_SLA",
    "ESCALATE_SLA",
    "SUBMIT_RECOVERY_PLAN",
    "UPDATE_JOB_STATUS",
    "MOVE_JOB_STAGE",
    "CREATE_PROCUREMENT",
    "EVALUATE_SLA",
}


class OmniAssistantUseCase:
    """
    Builds a live, structured SQL snapshot of the entire PRIMA workspace
    (Procurements, Deadlines/SLA, AI Validation Logs, Documents, Guarantees, and Templates)
    and executes the Omni-Search Generative AI query strictly in 'cekatan' mode.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _build_workspace_snapshot(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        today = now.date()

        # 1. Procurement Requests
        req_res = await self.session.execute(
            select(ProcurementRequestModel).order_by(desc(ProcurementRequestModel.updated_at)).limit(40)
        )
        requests = req_res.scalars().all()
        req_map = {r.id: r.title for r in requests}

        requests_summary = [
            {
                "id": r.id,
                "title": r.title,
                "stage": r.stage,
                "current_step": r.current_step,
                "operational_status": r.operational_status,
                "operational_status_reason": r.operational_status_reason,
                "procurement_method": r.procurement_method,
                "amount_idr": r.amount,
                "pic_name": r.pic_name,
                "fpp_name": r.fpp_name,
                "department": r.department_name,
                "is_urgent": bool(r.is_urgent),
            }
            for r in requests
        ]

        # 2. Deadlines / SLA
        dl_res = await self.session.execute(
            select(DeadlineModel).order_by(DeadlineModel.target_date).limit(50)
        )
        deadlines = dl_res.scalars().all()
        deadlines_summary = []
        for d in deadlines:
            t_date = d.target_date.date() if hasattr(d.target_date, "date") else today
            days_rem = (t_date - today).days
            effective_status = (
                "Selesai"
                if d.status == "Selesai"
                else ("Overdue" if days_rem < 0 else d.status)
            )
            deadlines_summary.append(
                {
                    "id": d.id,
                    "request_id": d.request_id,
                    "request_title": req_map.get(d.request_id, d.request_id),
                    "task_name": d.task_name,
                    "milestone": d.milestone,
                    "pic_name": d.pic_name,
                    "department": d.department_name,
                    "target_date": t_date.isoformat(),
                    "days_remaining": days_rem,
                    "status": effective_status,
                    "urgency_level": d.urgency_level,
                    "is_escalated": bool(d.is_escalated),
                    "escalated_to": d.escalated_to,
                    "overdue_reason": d.overdue_reason,
                    "recovery_plan": d.recovery_plan,
                }
            )

        # 3. AI Validation Logs (include executive summary & failed/warning items)
        val_res = await self.session.execute(
            select(DocumentValidationLogModel)
            .order_by(desc(DocumentValidationLogModel.created_at))
            .limit(30)
        )
        val_logs = val_res.scalars().all()
        validations_summary = []
        for v in val_logs:
            v_res_json = v.validation_result if isinstance(v.validation_result, dict) else {}
            evals = v_res_json.get("checklist_evaluations") or []
            failed_items = [
                f"{e.get('item')} ({e.get('status')}: {e.get('explanation') or ''})"
                for e in evals
                if isinstance(e, dict) and e.get("status") != "Memenuhi"
            ][:5]
            validations_summary.append(
                {
                    "id": v.id,
                    "document_id": v.document_id,
                    "request_id": v.request_id,
                    "document_name": v.document_name,
                    "profile_name": v.profile_name,
                    "overall_score": round(float(v.overall_score or 0.0), 1),
                    "compliance_status": v.compliance_status,
                    "processing_status": v.processing_status,
                    "executive_summary": (v_res_json.get("executive_summary") or "")[:320],
                    "attention_or_failed_items": failed_items,
                    "validated_at": v.created_at.strftime("%Y-%m-%d") if v.created_at else None,
                }
            )

        # 4. Documents
        doc_res = await self.session.execute(
            select(DocumentModel).order_by(desc(DocumentModel.upload_date)).limit(30)
        )
        docs = doc_res.scalars().all()
        documents_summary = [
            {
                "id": doc.id,
                "request_id": doc.request_id,
                "name": doc.name,
                "document_kind": doc.document_kind,
                "status": doc.status,
                "pic_name": doc.pic_name,
                "issues": (doc.issues or [])[:3],
                "next_action": doc.next_action,
            }
            for doc in docs
        ]

        # 5. Guarantees (Warkat Jaminan)
        guar_res = await self.session.execute(
            select(GuaranteeModel).order_by(GuaranteeModel.expiry_date).limit(30)
        )
        guarantees = guar_res.scalars().all()
        guarantees_summary = [
            {
                "id": g.id,
                "request_id": g.request_id,
                "reference_no": g.reference_no,
                "type": g.type,
                "vendor_name": g.vendor_name,
                "issuer": g.issuer,
                "value_idr": g.value,
                "expiry_date": g.expiry_date.strftime("%Y-%m-%d") if g.expiry_date else None,
                "status": g.status,
            }
            for g in guarantees
        ]

        # 6. Validation Templates
        prof_res = await self.session.execute(
            select(ValidationProfileModel).where(ValidationProfileModel.is_active == True).limit(20)
        )
        profiles = prof_res.scalars().all()
        templates_summary = [
            {
                "id": p.id,
                "name": p.name,
                "document_kind": p.document_kind,
                "passing_score_threshold": p.passing_score_threshold,
                "criteria_count": len(p.checklist_rules or []),
            }
            for p in profiles
        ]

        return {
            "current_date": today.isoformat(),
            "summary_counts": {
                "total_procurements": len(requests_summary),
                "active_procurements": sum(
                    1 for r in requests_summary if r["operational_status"] == "On Going" and r["stage"] != "Selesai"
                ),
                "overdue_slas": sum(1 for d in deadlines_summary if d["status"] == "Overdue"),
                "escalated_slas": sum(1 for d in deadlines_summary if d["is_escalated"]),
                "total_ai_validations": len(validations_summary),
                "total_guarantees": len(guarantees_summary),
            },
            "procurement_requests": requests_summary,
            "sla_deadlines": deadlines_summary,
            "ai_validation_logs": validations_summary,
            "documents": documents_summary,
            "guarantees": guarantees_summary,
            "validation_templates": templates_summary,
        }

    async def execute(
        self,
        query: str,
        history: List[OmniChatHistoryTurnDto] | None = None,
        attachment_bytes: bytes | None = None,
        attachment_mime: str | None = None,
        attachment_filename: str | None = None,
        page_context: str | None = None,
    ) -> OmniAssistantResponseDto:
        snapshot = await self._build_workspace_snapshot()
        context_json = json.dumps(snapshot, ensure_ascii=False)

        # Sync any saved external AI provider configuration from system_settings
        try:
            from src.presentation.api.v1.integrations import _load_synced_integration_config
            await _load_synced_integration_config(self.session)
        except Exception:
            pass

        history_lines: List[str] = []
        if history:
            for turn in history[-8:]:
                speaker = "Pengguna" if turn.role == "user" else "PRIMA AI"
                history_lines.append(f"- {speaker}: {turn.content}")
        history_text = "\n".join(history_lines)

        # Check if External Agent Takeover (mcp_takeover) is active for Chat
        ext_mode = str(gemini_service.external_config.get("provider_mode") or "internal_gemini")
        if ext_mode == "mcp_takeover" and gemini_service.external_config.get("replace_chat_brain", True):
            extracted_att = ""
            if attachment_bytes and attachment_filename:
                extracted_att = gemini_service._extract_document_text(
                    attachment_bytes,
                    (attachment_mime or "application/octet-stream").lower(),
                    attachment_filename,
                )
            ticket = gemini_service.enqueue_takeover_ticket(
                user_query=query,
                page_context=page_context or "",
                attachment_filename=attachment_filename,
                attachment_extracted_text=extracted_att,
                conversation_history_text=history_text,
                workspace_summary=snapshot,
            )
            return OmniAssistantResponseDto(
                intent_kind="QUESTION",
                answer=(
                    f"Pesan Anda telah diteruskan ke antrean **External Agent Takeover** dengan kode tiket **`{ticket['ticket_id']}`**.\n\n"
                    "Silakan perintahkan AI Eksternal Anda (Antigravity / Claude Code / Codex / Cursor) untuk memanggil tool MCP "
                    "`prima_get_pending_chat_takeover` dan membalas melalui `prima_reply_chat_takeover` (atau balas langsung dari tab Pengaturan → Integrasi)."
                ),
                highlights=[
                    f"ID Tiket Takeover: {ticket['ticket_id']}",
                    "Status: Menunggu respons dari Agent Eksternal (Auto-refresh aktif)",
                ],
                referenced_items=[],
                command=None,
                suggested_followups=[],
                ai_tier_requested="mcp_takeover",
                ai_tier_used="mcp_takeover",
                ai_model_used="External Agent Takeover (Waiting)",
                ai_fallback_notice=None,
                takeover_ticket_id=ticket["ticket_id"],
                takeover_pending=True,
            )

        raw_parsed, ai_meta = await gemini_service.generate_omni_assistant_response(
            user_query=query,
            workspace_context_json=context_json,
            conversation_history_text=history_text,
            attachment_bytes=attachment_bytes,
            attachment_mime=attachment_mime,
            attachment_filename=attachment_filename,
            page_context_text=page_context or "",
        )

        intent_kind = str(raw_parsed.get("intent_kind") or "QUESTION").upper()
        if intent_kind not in {"QUESTION", "COMMAND", "HYBRID"}:
            intent_kind = "QUESTION"

        answer = str(raw_parsed.get("answer") or "Berikut hasil analisis dari data PRIMA.").strip()

        raw_highlights = raw_parsed.get("highlights")
        highlights: List[str] = []
        if isinstance(raw_highlights, list):
            highlights = [str(h).strip() for h in raw_highlights if str(h).strip()][:4]

        raw_refs = raw_parsed.get("referenced_items")
        referenced_items: List[OmniReferencedItemDto] = []
        if isinstance(raw_refs, list):
            for r in raw_refs[:6]:
                if not isinstance(r, dict) or not r.get("title"):
                    continue
                referenced_items.append(
                    OmniReferencedItemDto(
                        id=str(r.get("id") or "ref"),
                        category=str(r.get("category") or "Data PRIMA"),
                        title=str(r.get("title")),
                        subtitle=str(r.get("subtitle") or ""),
                        badge=str(r.get("badge")) if r.get("badge") else None,
                        is_urgent=bool(r.get("is_urgent", False)),
                        href=str(r.get("href")) if r.get("href") else None,
                    )
                )

        command_dto = None
        raw_cmd = raw_parsed.get("command")
        if isinstance(raw_cmd, dict):
            cmd_type = str(raw_cmd.get("type") or "").upper()
            if cmd_type in _ALLOWED_COMMAND_TYPES:
                command_dto = OmniCommandDto(
                    type=cmd_type,  # type: ignore[arg-type]
                    label=str(raw_cmd.get("label") or "Jalankan Perintah"),
                    description=str(raw_cmd.get("description") or "") or None,
                    auto_execute=bool(raw_cmd.get("auto_execute", False)),
                    params=raw_cmd.get("params") if isinstance(raw_cmd.get("params"), dict) else {},
                )

        raw_followups = raw_parsed.get("suggested_followups")
        suggested_followups: List[str] = []
        if isinstance(raw_followups, list):
            suggested_followups = [str(f).strip() for f in raw_followups if str(f).strip()][:3]

        return OmniAssistantResponseDto(
            intent_kind=intent_kind,  # type: ignore[arg-type]
            answer=answer,
            highlights=highlights,
            referenced_items=referenced_items,
            command=command_dto,
            suggested_followups=suggested_followups,
            ai_tier_requested=str(ai_meta.get("ai_tier_requested") or "cekatan"),
            ai_tier_used=str(ai_meta.get("ai_tier_used") or "cekatan"),
            ai_model_used=ai_meta.get("ai_model_used"),
            ai_fallback_notice=ai_meta.get("ai_fallback_notice"),
        )
