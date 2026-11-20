"""
PRIMA External AI Integration & Model Context Protocol (MCP) Server Router
- Exposes JSON-RPC 2.0 MCP endpoint (/api/v1/integrations/mcp) with 100% full-system CRUD & analysis tools
- Manages Pluggable External AI Provider configuration
- Generates long-lived Personal Access Tokens (PAT) for Antigravity, Codex, Claude Code, Cursor, and ChatGPT Actions
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import get_db
from src.infrastructure.models.settings_model import SettingsModel
from src.infrastructure.models.user_model import UserModel
from src.infrastructure.models.procurement_model import (
    ProcurementRequestModel,
    ProcurementMilestoneModel,
)
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.guarantee_model import GuaranteeModel
from src.infrastructure.models.document_model import DocumentModel
from src.infrastructure.models.notification_model import NotificationModel
from src.infrastructure.models.activity_model import ProcurementActivityLogModel
from src.infrastructure.models.validation_model import (
    DocumentValidationLogModel,
    ValidationProfileModel,
)
from src.infrastructure.models.workflow_stage_model import WorkflowStageModel
from src.infrastructure.storage.s3_service import s3_service
from src.infrastructure.ai.gemini_service import gemini_service
from src.infrastructure.security.jwt import create_agent_api_token
from src.presentation.auth_dependencies import get_current_user
from src.application.dtos.response_wrapper import success_response
from src.application.dtos.validation_dto import (
    CreateValidationProfileDto,
    UpdateValidationProfileDto,
    PublishValidationToTrackerRequestDto,
    UpdateValidationDecisionDto,
    WorkflowStageCreateDto,
    WorkflowStageUpdateDto,
    WorkflowStageReorderDto,
)
from src.application.use_cases.omni_assistant_use_case import OmniAssistantUseCase
from src.application.use_cases.procurement_use_cases import (
    CreateProcurementUseCase,
    MoveStageUseCase,
    MoveStepUseCase,
    UpdateOperationalStatusUseCase,
    AssignPicUseCase,
    UpdateMilestonesUseCase,
)
from src.application.use_cases.validation_use_cases import (
    ManageValidationProfilesUseCase,
    ManageWorkflowStagesUseCase,
    PublishValidationToTrackerUseCase,
    GetValidationLogsUseCase,
)
from src.infrastructure.repositories.procurement_repository import PostgresProcurementRepository

router = APIRouter(prefix="/integrations", tags=["External AI & MCP Integrations"])

_INTEGRATION_STORAGE_KEY = "__ai_integration_config__"


class CustomAiModelPayload(BaseModel):
    id: Optional[str] = None
    display_name: str
    provider_kind: str = Field(
        default="external_api",
        description="external_mcp | external_api | external_webhook",
    )
    provider_name: Optional[str] = Field(default="")
    base_url: Optional[str] = Field(default="https://api.openai.com/v1")
    api_key: Optional[str] = Field(default=None)
    model_name: Optional[str] = Field(default="gpt-4o-mini")
    enable_chat: bool = Field(default=True)
    enable_analysis: bool = Field(default=True)
    clear_api_key: bool = Field(default=False)


class AiIntegrationConfigPayload(BaseModel):
    provider_mode: str = Field(
        default="internal_gemini",
        description="internal_gemini | external_mcp | external_api | external_webhook",
    )
    provider_name: str = Field(default="PRIMA Internal (Google Gemini)")
    base_url: str = Field(default="https://api.openai.com/v1")
    api_key: Optional[str] = Field(default=None)
    model_name: str = Field(default="gpt-4o-mini")
    replace_chat_brain: bool = Field(default=True)
    replace_analysis_brain: bool = Field(default=True)
    active_custom_model_id: Optional[str] = Field(default=None)
    custom_models: Optional[List[CustomAiModelPayload]] = Field(default=None)


class GenerateTokenPayload(BaseModel):
    label: str = Field(default="Antigravity / MCP Agent Key")
    expires_days: int = Field(default=365, ge=1, le=3650)


class McpToolExecutePayload(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


MCP_TOOLS_CATALOG: List[Dict[str, Any]] = [
    {
        "name": "prima_get_workspace_snapshot",
        "description": "Membaca seluruh snapshot data real-time PRIMA (Pekerjaan Pengadaan, SLA/Deadlines, Hasil Validasi AI, Dokumen, Warkat Jaminan, dan Template Kriteria).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "prima_create_procurement",
        "description": "Membuat paket pekerjaan pengadaan baru di PRIMA beserta milestone tahapan dan target SLA otomatis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Judul paket pekerjaan pengadaan"},
                "amount": {"type": "number", "description": "Nilai anggaran dalam Rupiah (IDR)"},
                "department_name": {"type": "string", "description": "Nama departemen pemohon"},
                "procurement_method": {"type": "string", "description": "Metode pengadaan (mis. Tender Terbuka, Pemilihan Langsung, Penunjukan Langsung, atau custom)"},
                "is_urgent": {"type": "boolean", "description": "Status prioritas urgent"},
                "pic_name": {"type": "string", "description": "Opsional: Nama PIC pengadaan"},
            },
            "required": ["title", "amount"],
        },
    },
    {
        "name": "prima_update_procurement_stage_or_status",
        "description": "Memindahkan tahapan (step/stage) atau mengubah status operasional (On Going / On Hold / Batal) pada pekerjaan pengadaan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "ID Pekerjaan (mis. REQ-...)"},
                "new_stage": {"type": "string", "description": "Opsional: Persiapan | Sourcing | Evaluasi | Contracting | Selesai"},
                "new_step": {"type": "string", "description": "Opsional: Nama langkah spesifik"},
                "operational_status": {"type": "string", "description": "Opsional: On Going | On Hold | Batal"},
                "notes": {"type": "string", "description": "Catatan atau alasan perubahan"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "prima_manage_procurement_full",
        "description": "Operasi penuh pada paket pekerjaan pengadaan: edit detail/anggaran/metode (UPDATE_DETAILS), delegasi/handover PIC (ASSIGN_PIC), ubah urutan milestone pekerjaan (UPDATE_MILESTONES), atau hapus pekerjaan permanen (DELETE).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["UPDATE_DETAILS", "ASSIGN_PIC", "UPDATE_MILESTONES", "DELETE"],
                },
                "request_id": {"type": "string", "description": "ID Pekerjaan target"},
                "title": {"type": "string"},
                "amount": {"type": "number"},
                "department_name": {"type": "string"},
                "procurement_method": {"type": "string"},
                "is_urgent": {"type": "boolean"},
                "new_pic_id": {"type": "string"},
                "new_pic_name": {"type": "string"},
                "handover_notes": {"type": "string"},
                "milestones": {
                    "type": "array",
                    "description": "Untuk UPDATE_MILESTONES: daftar [{step, status, notes}]",
                    "items": {"type": "object"},
                },
            },
            "required": ["action", "request_id"],
        },
    },
    {
        "name": "prima_manage_sla_deadline",
        "description": "CRUD & manajemen penuh jadwal Target SLA: buat SLA baru (CREATE), ubah tanggal/detail SLA (UPDATE), tandai selesai (COMPLETE), eskalasi manajer (ESCALATE), simpan rencana mitigasi (RECOVERY_PLAN), hapus SLA (DELETE), atau evaluasi massal seluruh SLA (EVALUATE_ALL).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "CREATE",
                        "UPDATE",
                        "COMPLETE",
                        "ESCALATE",
                        "RECOVERY_PLAN",
                        "DELETE",
                        "EVALUATE_ALL",
                    ],
                },
                "deadline_id": {"type": "string", "description": "ID SLA / Deadline (wajib kecuali CREATE / EVALUATE_ALL)"},
                "request_id": {"type": "string", "description": "ID Pekerjaan (untuk CREATE atau filter EVALUATE_ALL)"},
                "task_name": {"type": "string"},
                "milestone": {"type": "string"},
                "target_date": {"type": "string", "description": "Format ISO YYYY-MM-DD"},
                "urgency_level": {"type": "string", "enum": ["Low", "Medium", "High", "Critical"]},
                "pic_name": {"type": "string"},
                "department_name": {"type": "string"},
                "escalated_to": {"type": "string"},
                "reason_or_plan": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "prima_manage_guarantee",
        "description": "CRUD & manajemen siklus hidup Warkat Jaminan (Modul D2): buat warkat baru (CREATE), edit warkat (UPDATE), ajukan klaim (CLAIM), perpanjang/amandemen (AMEND), kembalikan BAST (RELEASE), atau hapus warkat (DELETE).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["CREATE", "UPDATE", "CLAIM", "AMEND", "RELEASE", "DELETE"],
                },
                "guarantee_id": {"type": "string", "description": "ID Warkat Jaminan (mis. G-...)"},
                "request_id": {"type": "string", "description": "ID Pekerjaan terkait (untuk CREATE)"},
                "reference_no": {"type": "string"},
                "type": {
                    "type": "string",
                    "description": "Jaminan Pelaksanaan | Jaminan Masa Pemeliharaan | Jaminan Uang Muka",
                },
                "value": {"type": "number"},
                "issuer": {"type": "string"},
                "issuer_type": {"type": "string", "enum": ["Bank", "Asuransi", "Lainnya"]},
                "vendor_name": {"type": "string"},
                "issue_date": {"type": "string", "description": "YYYY-MM-DD"},
                "expiry_date": {"type": "string", "description": "YYYY-MM-DD"},
                "claim_letter_no": {"type": "string"},
                "claim_reason": {"type": "string"},
                "amendment_no": {"type": "string"},
                "new_expiry_date": {"type": "string", "description": "YYYY-MM-DD"},
                "new_value": {"type": "number"},
                "bast_no": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "prima_manage_validation_template",
        "description": "CRUD Pustaka Template Kriteria Standar Kelayakan Dokumen (validation_profiles): lihat semua detail kriteria (LIST / GET_DETAIL), buat template baru (CREATE), edit template (UPDATE), atau hapus/nonaktifkan template (DELETE).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["LIST", "GET_DETAIL", "CREATE", "UPDATE", "DELETE"],
                },
                "profile_id": {"type": "string"},
                "name": {"type": "string"},
                "document_kind": {"type": "string"},
                "description": {"type": "string"},
                "scope": {"type": "string", "description": "GLOBAL | IT | INFRASTRUCTURE | SERVICES"},
                "passing_score_threshold": {"type": "number"},
                "target_stage_to_clear": {"type": "string"},
                "custom_system_prompt": {"type": "string"},
                "checklist_rules": {
                    "type": "array",
                    "description": "Daftar [{category, item, guidance, is_mandatory, weight}]",
                    "items": {"type": "object"},
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "prima_manage_workflow_stages",
        "description": "CRUD & Reorder Metode Pengadaan dan Tahapan Pekerjaan (workflow_stages): lihat daftar tahapan (LIST), tambah tahapan (CREATE_STAGE), edit tahapan/SLA (UPDATE_STAGE), urutkan ulang tahapan (REORDER_METHOD), hapus tahapan (DELETE_STAGE), atau hapus seluruh metode (DELETE_METHOD).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "LIST",
                        "CREATE_STAGE",
                        "UPDATE_STAGE",
                        "REORDER_METHOD",
                        "DELETE_STAGE",
                        "DELETE_METHOD",
                    ],
                },
                "stage_id": {"type": "string"},
                "procurement_method": {"type": "string"},
                "step_name": {"type": "string"},
                "stage_group": {"type": "string", "description": "Persiapan | Sourcing | Evaluasi | Contracting | Selesai"},
                "default_sla_days": {"type": "integer"},
                "description": {"type": "string"},
                "ordered_stage_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "prima_create_custom_method",
        "description": "Membuat metode pengadaan custom baru beserta urutan tahapan dan standar SLA hariannya dalam satu panggilan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "method_name": {"type": "string", "description": "Nama metode pengadaan baru"},
                "stages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_name": {"type": "string"},
                            "stage_group": {"type": "string"},
                            "default_sla_days": {"type": "integer"},
                        },
                        "required": ["step_name"],
                    },
                },
            },
            "required": ["method_name", "stages"],
        },
    },
    {
        "name": "prima_manage_document_and_validation",
        "description": "Operasi lengkap pada Dokumen & Hasil Validasi AI: ambil detail evaluasi checklist & Signed URL S3 berkas (GET_DETAIL_OR_FILE_URL), terbitkan hasil validasi ke Tracker Pekerjaan (PUBLISH_TO_TRACKER), ubah keputusan verifikasi (UPDATE_DECISION), atau hapus dokumen/log validasi (DELETE).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "GET_DETAIL_OR_FILE_URL",
                        "PUBLISH_TO_TRACKER",
                        "UPDATE_DECISION",
                        "DELETE",
                    ],
                },
                "id": {"type": "string", "description": "ID Validasi (VAL-...) atau ID Dokumen (DOC-...)"},
                "target_request_id": {"type": "string", "description": "Opsional untuk PUBLISH_TO_TRACKER ke pekerjaan yang sudah ada"},
                "title": {"type": "string"},
                "amount": {"type": "number"},
                "procurement_method": {"type": "string"},
                "department_name": {"type": "string"},
                "compliance_status": {
                    "type": "string",
                    "enum": ["Lulus Verifikasi", "Catatan Procurement", "Perlu Perbaikan"],
                },
                "overall_score": {"type": "number"},
                "reviewer_notes": {"type": "string"},
                "next_action": {"type": "string"},
            },
            "required": ["action", "id"],
        },
    },
    {
        "name": "prima_submit_external_document_analysis",
        "description": "Menyimpan hasil analisis/audit dokumen yang dikerjakan oleh AI Eksternal langsung ke dalam log pemeriksaan dokumen PRIMA.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_name": {"type": "string"},
                "request_id": {"type": "string"},
                "overall_score": {"type": "number"},
                "compliance_status": {"type": "string", "enum": ["Lulus Verifikasi", "Catatan Procurement", "Perlu Perbaikan"]},
                "executive_summary": {"type": "string"},
                "external_model_name": {"type": "string"},
                "recommendations": {"type": "array", "items": {"type": "string"}},
                "checklist_evaluations": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["document_name", "overall_score", "executive_summary"],
        },
    },
    {
        "name": "prima_manage_users_notifications_settings",
        "description": "Manajemen daftar pengguna/PIC (LIST_USERS), notifikasi sistem (LIST_NOTIFICATIONS, CREATE_NOTIFICATION, MARK_ALL_NOTIFICATIONS_READ), dan pengaturan sistem PRIMA (GET_SETTINGS, UPDATE_SETTINGS).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "LIST_USERS",
                        "LIST_NOTIFICATIONS",
                        "CREATE_NOTIFICATION",
                        "MARK_ALL_NOTIFICATIONS_READ",
                        "GET_SETTINGS",
                        "UPDATE_SETTINGS",
                    ],
                },
                "title": {"type": "string"},
                "description": {"type": "string"},
                "request_id": {"type": "string"},
                "notification_type": {"type": "string", "enum": ["system", "alert", "deadline", "document", "success"]},
                "action_url": {"type": "string"},
                "sla_warning_days": {"type": "integer"},
                "auto_escalation": {"type": "boolean"},
                "auto_escalate_days": {"type": "integer"},
                "approval_threshold": {"type": "number"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "prima_ask_or_command",
        "description": "Menjalankan pertanyaan atau perintah bahasa natural melalui router Omni-Assistant PRIMA.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Pertanyaan atau perintah bahasa natural"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "prima_get_pending_chat_takeover",
        "description": "Mengambil daftar pesan/pertanyaan dari pengguna di ruang Diskusi AI web PRIMA yang sedang menunggu dijawab oleh AI Eksternal (Mode External Agent Takeover).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_workspace_snapshot": {
                    "type": "boolean",
                    "description": "Sertakan snapshot lengkap database PRIMA agar agent eksternal dapat menjawab dengan akurat",
                }
            },
        },
    },
    {
        "name": "prima_reply_chat_takeover",
        "description": "Mengirimkan jawaban dan perintah (command) dari AI Eksternal langsung ke dalam bubble chat pengguna di web PRIMA yang sedang menunggu (Mode External Agent Takeover).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "ID Tiket Takeover (mis. TKT-...) atau isi 'LATEST' untuk membalas pesan terbaru",
                },
                "answer": {
                    "type": "string",
                    "description": "Jawaban lengkap dari AI Eksternal untuk ditampilkan di bubble chat PRIMA",
                },
                "agent_name": {
                    "type": "string",
                    "description": "Nama AI Eksternal yang menjawab (mis. 'Antigravity Agent', 'Claude Code', 'Codex')",
                },
                "highlights": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Opsional: poin-poin ringkasan utama",
                },
                "referenced_items": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Opsional: daftar kartu referensi [{id, category, title, subtitle, badge, is_urgent, href}]",
                },
                "command": {
                    "type": "object",
                    "description": "Opsional: objek perintah PRIMA {type, label, description, params}",
                },
                "suggested_followups": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["ticket_id", "answer"],
        },
    },
]


def _parse_iso_date(val: Any, fallback_days_offset: int = 0) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, str) and val.strip():
        clean = val.strip()
        try:
            if "T" in clean:
                return datetime.fromisoformat(clean.replace("Z", "+00:00"))
            return datetime.fromisoformat(f"{clean}T00:00:00+00:00")
        except Exception:
            pass
    return datetime.now(timezone.utc) + timedelta(days=fallback_days_offset)


async def _load_synced_integration_config(session: AsyncSession) -> Dict[str, Any]:
    res = await session.execute(select(SettingsModel).where(SettingsModel.id == "1"))
    st = res.scalar_one_or_none()
    if st and isinstance(st.department_reviewers, dict):
        raw_json = st.department_reviewers.get(_INTEGRATION_STORAGE_KEY)
        if raw_json:
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict):
                    gemini_service.set_external_config(parsed)
            except Exception:
                pass
    return gemini_service.get_external_config_masked()


async def _execute_mcp_tool(
    tool_name: str,
    args: Dict[str, Any],
    db: AsyncSession,
    user: UserModel,
) -> Dict[str, Any]:
    # 1. SNAPSHOT
    if tool_name == "prima_get_workspace_snapshot":
        uc = OmniAssistantUseCase(db)
        return await uc._build_workspace_snapshot()

    # 2. CREATE PROCUREMENT
    if tool_name == "prima_create_procurement":
        repo = PostgresProcurementRepository(db)
        uc = CreateProcurementUseCase(repo)
        created = await uc.execute(
            title=str(args.get("title") or "Pekerjaan Baru via External AI"),
            pic_id=user.id,
            pic_name=str(args.get("pic_name") or user.name),
            fpp_id="FPP-EXT",
            fpp_name=str(args.get("department_name") or "Procurement"),
            amount=float(args.get("amount") or 100000000),
            department_id="DEPT-PROC",
            department_name=str(args.get("department_name") or "Procurement"),
            stage="Persiapan",
            current_step="Rapat Pra-Tender",
            procurement_method=str(args.get("procurement_method") or "Tender Terbuka"),
            is_urgent=bool(args.get("is_urgent", False)),
        )
        return {
            "created_request_id": created.id,
            "title": created.title,
            "stage": created.stage,
            "current_step": created.current_step,
            "method": created.procurement_method,
            "amount": created.amount,
        }

    # 3. UPDATE STAGE / STEP / STATUS
    if tool_name == "prima_update_procurement_stage_or_status":
        req_id = str(args.get("request_id") or "").strip()
        if not req_id:
            raise ValueError("request_id wajib diisi")
        repo = PostgresProcurementRepository(db)
        notes = str(args.get("notes") or "Diperbarui oleh External AI Agent via MCP")

        if args.get("operational_status"):
            uc_stat = UpdateOperationalStatusUseCase(repo)
            updated = await uc_stat.execute(req_id, str(args["operational_status"]), notes)
        elif args.get("new_step"):
            uc_step = MoveStepUseCase(repo)
            updated = await uc_step.execute(req_id, str(args["new_step"]), force=True, override_reason=notes)
        elif args.get("new_stage"):
            uc_stg = MoveStageUseCase(repo)
            updated = await uc_stg.execute(req_id, str(args["new_stage"]), notes)
        else:
            raise ValueError("Sertakan salah satu dari operational_status, new_step, atau new_stage")

        return {
            "request_id": updated.id,
            "title": updated.title,
            "stage": updated.stage,
            "current_step": updated.current_step,
            "operational_status": updated.operational_status,
        }

    # 4. FULL PROCUREMENT MANAGEMENT (UPDATE_DETAILS, ASSIGN_PIC, UPDATE_MILESTONES, DELETE)
    if tool_name == "prima_manage_procurement_full":
        action = str(args.get("action") or "").upper()
        req_id = str(args.get("request_id") or "").strip()
        if not req_id:
            raise ValueError("request_id wajib diisi")

        res = await db.execute(select(ProcurementRequestModel).where(ProcurementRequestModel.id == req_id))
        proc = res.scalar_one_or_none()
        if not proc:
            raise ValueError(f"Pekerjaan '{req_id}' tidak ditemukan")

        if action == "DELETE":
            title_backup = proc.title
            await db.delete(proc)
            await db.commit()
            return {"deleted_request_id": req_id, "deleted_title": title_backup}

        if action == "UPDATE_DETAILS":
            if args.get("title") is not None:
                proc.title = str(args["title"]).strip()
            if args.get("amount") is not None:
                proc.amount = float(args["amount"])
            if args.get("department_name") is not None:
                proc.department_name = str(args["department_name"]).strip()
            if args.get("procurement_method") is not None:
                proc.procurement_method = str(args["procurement_method"]).strip()
            if args.get("is_urgent") is not None:
                proc.is_urgent = bool(args["is_urgent"])
            proc.updated_at = datetime.now(timezone.utc)
            await db.commit()
            return {
                "request_id": proc.id,
                "title": proc.title,
                "amount": proc.amount,
                "department_name": proc.department_name,
                "procurement_method": proc.procurement_method,
                "is_urgent": proc.is_urgent,
            }

        if action == "ASSIGN_PIC":
            repo = PostgresProcurementRepository(db)
            uc_pic = AssignPicUseCase(repo)
            updated = await uc_pic.execute(
                request_id=req_id,
                new_pic_id=str(args.get("new_pic_id") or user.id),
                new_pic_name=str(args.get("new_pic_name") or user.name),
                handover_notes=str(args.get("handover_notes") or "Delegasi PIC via MCP Agent"),
            )
            return {
                "request_id": updated.id,
                "new_pic_id": updated.pic.id,
                "new_pic_name": updated.pic.name,
            }

        if action == "UPDATE_MILESTONES":
            ms_list = args.get("milestones")
            if not isinstance(ms_list, list) or not ms_list:
                raise ValueError("Field 'milestones' (list) wajib diisi untuk UPDATE_MILESTONES")
            repo = PostgresProcurementRepository(db)
            uc_ms = UpdateMilestonesUseCase(repo)
            updated_ms = await uc_ms.execute(
                request_id=req_id,
                milestones_payload=ms_list,
                actor_id=user.id,
                actor_name=user.name,
                notes="Milestones diperbarui via MCP Agent",
            )
            return {
                "request_id": req_id,
                "milestones_count": len(updated_ms),
                "milestones": [{"step": m.step, "status": m.status} for m in updated_ms],
            }

        raise ValueError(f"Action '{action}' tidak dikenal pada prima_manage_procurement_full")

    # 5. SLA DEADLINES FULL CRUD & MASS EVALUATION
    if tool_name == "prima_manage_sla_deadline":
        action = str(args.get("action") or "COMPLETE").upper()
        now = datetime.now(timezone.utc)

        if action == "EVALUATE_ALL":
            from src.presentation.api.v1.deadlines import evaluate_sla
            eval_res = await evaluate_sla(request_id=args.get("request_id"), db=db)
            return eval_res.get("data", {})

        if action == "CREATE":
            req_id = str(args.get("request_id") or "").strip()
            if not req_id:
                raise ValueError("request_id wajib diisi untuk membuat SLA baru")
            new_dl = DeadlineModel(
                id=f"D-{uuid.uuid4().hex[:8].upper()}",
                request_id=req_id,
                task_name=str(args.get("task_name") or "Target SLA Baru"),
                milestone=str(args.get("milestone") or "Rapat Pra-Tender"),
                pic_id=user.id,
                pic_name=str(args.get("pic_name") or user.name),
                department_id="DEPT-PROC",
                department_name=str(args.get("department_name") or "Procurement"),
                start_date=now,
                target_date=_parse_iso_date(args.get("target_date"), fallback_days_offset=5),
                status="On Track",
                urgency_level=str(args.get("urgency_level") or "Medium"),
                next_action=str(args.get("reason_or_plan") or "Selesaikan tahapan sesuai jadwal SLA."),
                created_at=now,
                updated_at=now,
            )
            db.add(new_dl)
            await db.commit()
            return {
                "created_deadline_id": new_dl.id,
                "task_name": new_dl.task_name,
                "target_date": new_dl.target_date.isoformat(),
                "status": new_dl.status,
            }

        dl_id = str(args.get("deadline_id") or "").strip()
        res = await db.execute(select(DeadlineModel).where(DeadlineModel.id == dl_id))
        dl = res.scalar_one_or_none()
        if not dl:
            raise ValueError(f"Deadline '{dl_id}' tidak ditemukan")

        if action == "DELETE":
            await db.delete(dl)
            await db.commit()
            return {"deleted_deadline_id": dl_id}

        if action == "UPDATE":
            if args.get("task_name"):
                dl.task_name = str(args["task_name"])
            if args.get("milestone"):
                dl.milestone = str(args["milestone"])
            if args.get("target_date"):
                dl.target_date = _parse_iso_date(args["target_date"])
            if args.get("urgency_level"):
                dl.urgency_level = str(args["urgency_level"])
            if args.get("pic_name"):
                dl.pic_name = str(args["pic_name"])
            if args.get("reason_or_plan"):
                dl.next_action = str(args["reason_or_plan"])
        elif action == "COMPLETE":
            dl.status = "Selesai"
        elif action == "ESCALATE":
            dl.is_escalated = True
            dl.escalated_at = now
            dl.escalated_to = str(args.get("escalated_to") or "Manager Pengadaan Korporat")
            dl.overdue_reason = str(args.get("reason_or_plan") or "Dieskalasi oleh External AI Agent")
        elif action == "RECOVERY_PLAN":
            dl.recovery_plan = str(args.get("reason_or_plan") or "Percepatan tahapan via External AI Agent")
            dl.recovery_date = _parse_iso_date(args.get("target_date"), fallback_days_offset=3)

        dl.updated_at = now
        await db.commit()
        return {
            "deadline_id": dl.id,
            "task_name": dl.task_name,
            "status": dl.status,
            "target_date": dl.target_date.isoformat() if dl.target_date else None,
            "is_escalated": dl.is_escalated,
            "recovery_plan": dl.recovery_plan,
        }

    # 6. GUARANTEES (WARKAT JAMINAN) FULL CRUD & LIFECYCLE
    if tool_name == "prima_manage_guarantee":
        action = str(args.get("action") or "").upper()
        now = datetime.now(timezone.utc)

        if action == "CREATE":
            req_id = str(args.get("request_id") or "").strip()
            if not req_id:
                raise ValueError("request_id wajib diisi untuk membuat Warkat Jaminan")
            g_id = f"G-{uuid.uuid4().hex[:8].upper()}"
            g_model = GuaranteeModel(
                id=g_id,
                request_id=req_id,
                reference_no=str(args.get("reference_no") or f"BG-{uuid.uuid4().hex[:6].upper()}"),
                type=str(args.get("type") or "Jaminan Pelaksanaan"),
                value=float(args.get("value") or 50000000),
                issuer=str(args.get("issuer") or "PT Bank Mandiri (Persero) Tbk"),
                issuer_type=str(args.get("issuer_type") or "Bank"),
                beneficiary="PT Pertamina Patra Niaga",
                vendor_id="V-MCP",
                vendor_name=str(args.get("vendor_name") or "PT Mitra Penyedia"),
                issue_date=_parse_iso_date(args.get("issue_date"), fallback_days_offset=0),
                expiry_date=_parse_iso_date(args.get("expiry_date"), fallback_days_offset=180),
                pic_id=user.id,
                pic_name=user.name,
                status="Aktif",
                created_at=now,
                updated_at=now,
            )
            db.add(g_model)
            await db.commit()
            return {
                "created_guarantee_id": g_model.id,
                "reference_no": g_model.reference_no,
                "type": g_model.type,
                "value": g_model.value,
                "status": g_model.status,
            }

        g_id = str(args.get("guarantee_id") or "").strip()
        res = await db.execute(select(GuaranteeModel).where(GuaranteeModel.id == g_id))
        g = res.scalar_one_or_none()
        if not g:
            raise ValueError(f"Warkat Jaminan '{g_id}' tidak ditemukan")

        if action == "DELETE":
            if g.file_url:
                s3_service.delete_file(g.file_url)
            await db.delete(g)
            await db.commit()
            return {"deleted_guarantee_id": g_id}

        if action == "UPDATE":
            for field in ("reference_no", "type", "issuer", "issuer_type", "vendor_name"):
                if args.get(field) is not None:
                    setattr(g, field, str(args[field]))
            if args.get("value") is not None:
                g.value = float(args["value"])
            if args.get("expiry_date"):
                g.expiry_date = _parse_iso_date(args["expiry_date"])
        elif action == "CLAIM":
            g.status = "Klaim Diajukan"
            g.next_action = f"Klaim diajukan (Surat: {args.get('claim_letter_no') or '-'}). Alasan: {args.get('claim_reason') or '-'}"
        elif action == "AMEND":
            if args.get("new_expiry_date"):
                g.expiry_date = _parse_iso_date(args["new_expiry_date"])
            if args.get("new_value") is not None:
                g.value = float(args["new_value"])
            g.status = "Aktif"
            g.next_action = f"Amandemen disetujui (No: {args.get('amendment_no') or '-'})"
        elif action == "RELEASE":
            g.status = "Dikembalikan"
            g.next_action = f"Warkat dikembalikan ke vendor (BAST: {args.get('bast_no') or '-'})"

        g.updated_at = now
        await db.commit()
        return {
            "guarantee_id": g.id,
            "reference_no": g.reference_no,
            "status": g.status,
            "value": g.value,
            "next_action": g.next_action,
        }

    # 7. VALIDATION TEMPLATES (PUSTAKA TEMPLATE KRITERIA) FULL CRUD
    if tool_name == "prima_manage_validation_template":
        action = str(args.get("action") or "LIST").upper()
        uc_prof = ManageValidationProfilesUseCase(db)

        if action == "LIST":
            profiles = await uc_prof.list_profiles(active_only=True)
            return {"templates": [p.model_dump(mode="json") for p in profiles]}

        if action == "GET_DETAIL":
            prof = await uc_prof.get_by_id(str(args.get("profile_id") or ""))
            return prof.model_dump(mode="json")

        if action == "CREATE":
            rules = args.get("checklist_rules") or [
                {"category": "Umum", "item": "Kesesuaian ruang lingkup & spesifikasi", "is_mandatory": True, "weight": 50},
                {"category": "Finansial & Harga", "item": "Kesesuaian nilai anggaran / HPS", "is_mandatory": True, "weight": 50},
            ]
            dto = CreateValidationProfileDto(
                name=str(args.get("name") or "Template Standar Baru via MCP"),
                document_kind=str(args.get("document_kind") or "Kerangka Acuan Kerja"),
                description=args.get("description"),
                scope=str(args.get("scope") or "GLOBAL"),
                passing_score_threshold=float(args.get("passing_score_threshold") or 80.0),
                target_stage_to_clear=args.get("target_stage_to_clear"),
                custom_system_prompt=args.get("custom_system_prompt"),
                checklist_rules=rules,
            )
            created = await uc_prof.create_profile(dto, actor_id=user.id, actor_name=user.name)
            return created.model_dump(mode="json")

        if action == "UPDATE":
            p_id = str(args.get("profile_id") or "").strip()
            update_payload = {
                k: args[k]
                for k in (
                    "name",
                    "document_kind",
                    "description",
                    "scope",
                    "passing_score_threshold",
                    "target_stage_to_clear",
                    "custom_system_prompt",
                    "checklist_rules",
                )
                if k in args and args[k] is not None
            }
            dto = UpdateValidationProfileDto(**update_payload)
            updated = await uc_prof.update_profile(p_id, dto, actor_id=user.id, actor_name=user.name)
            return updated.model_dump(mode="json")

        if action == "DELETE":
            p_id = str(args.get("profile_id") or "").strip()
            await uc_prof.delete_profile(p_id)
            return {"deleted_profile_id": p_id}

    # 8. WORKFLOW STAGES & METHODS FULL CRUD
    if tool_name == "prima_manage_workflow_stages":
        action = str(args.get("action") or "LIST").upper()
        uc_wf = ManageWorkflowStagesUseCase(db)

        if action == "LIST":
            stages = await uc_wf.list_stages(
                procurement_method=args.get("procurement_method"),
                active_only=True,
            )
            return {"stages": [s.model_dump(mode="json") for s in stages]}

        if action == "CREATE_STAGE":
            dto = WorkflowStageCreateDto(
                procurement_method=str(args.get("procurement_method") or "Tender Terbuka"),
                step_name=str(args.get("step_name") or "Tahapan Baru"),
                stage_group=str(args.get("stage_group") or "Sourcing"),
                default_sla_days=int(args.get("default_sla_days") or 5),
                description=args.get("description"),
            )
            created = await uc_wf.create_stage(dto)
            return created.model_dump(mode="json")

        if action == "UPDATE_STAGE":
            stg_id = str(args.get("stage_id") or "").strip()
            upd = {
                k: args[k]
                for k in ("procurement_method", "step_name", "stage_group", "default_sla_days", "description")
                if k in args and args[k] is not None
            }
            updated = await uc_wf.update_stage(stg_id, WorkflowStageUpdateDto(**upd))
            return updated.model_dump(mode="json")

        if action == "REORDER_METHOD":
            dto = WorkflowStageReorderDto(
                procurement_method=str(args.get("procurement_method") or "Tender Terbuka"),
                ordered_stage_ids=list(args.get("ordered_stage_ids") or []),
            )
            reordered = await uc_wf.reorder_stages(dto)
            return {"stages": [s.model_dump(mode="json") for s in reordered]}

        if action == "DELETE_STAGE":
            stg_id = str(args.get("stage_id") or "").strip()
            await uc_wf.delete_stage(stg_id)
            return {"deleted_stage_id": stg_id}

        if action == "DELETE_METHOD":
            method_name = str(args.get("procurement_method") or "").strip()
            await db.execute(
                update(WorkflowStageModel)
                .where(WorkflowStageModel.procurement_method == method_name)
                .values(is_active=False)
            )
            await db.commit()
            return {"deleted_method": method_name}

    # 9. CREATE CUSTOM METHOD BATCH
    if tool_name == "prima_create_custom_method":
        method_name = str(args.get("method_name") or "").strip()
        stages = args.get("stages") or []
        if not method_name or not isinstance(stages, list) or len(stages) == 0:
            raise ValueError("method_name dan stages wajib diisi")
        now = datetime.now(timezone.utc)
        created_ids = []
        for idx, s in enumerate(stages):
            if not isinstance(s, dict) or not s.get("step_name"):
                continue
            stg_id = f"STG-{uuid.uuid4().hex[:8].upper()}"
            db.add(WorkflowStageModel(
                id=stg_id,
                procurement_method=method_name,
                step_name=str(s["step_name"]).strip(),
                stage_group=str(s.get("stage_group") or "Sourcing"),
                order_index=idx,
                default_sla_days=int(s.get("default_sla_days") or 5),
                is_active=True,
                created_at=now,
                updated_at=now,
            ))
            created_ids.append(stg_id)
        await db.commit()
        return {
            "method_name": method_name,
            "stages_created": len(created_ids),
            "stage_ids": created_ids,
        }

    # 10. DOCUMENTS & VALIDATION LOGS (S3 VIEW URL, PUBLISH TO TRACKER, DECISION, DELETE)
    if tool_name == "prima_manage_document_and_validation":
        action = str(args.get("action") or "GET_DETAIL_OR_FILE_URL").upper()
        target_id = str(args.get("id") or "").strip()
        if not target_id:
            raise ValueError("Field 'id' (VAL-... atau DOC-...) wajib diisi")

        if action == "GET_DETAIL_OR_FILE_URL":
            uc_logs = GetValidationLogsUseCase(db)
            detail = await uc_logs.get_by_id(target_id)
            return detail.model_dump(mode="json")

        if action == "PUBLISH_TO_TRACKER":
            uc_pub = PublishValidationToTrackerUseCase(db)
            pub_dto = PublishValidationToTrackerRequestDto(
                validation_id=target_id,
                target_request_id=args.get("target_request_id"),
                title=args.get("title"),
                amount=float(args["amount"]) if args.get("amount") is not None else None,
                procurement_method=args.get("procurement_method"),
                department_name=args.get("department_name"),
            )
            return await uc_pub.execute(pub_dto, actor_id=user.id, actor_name=user.name)

        if action == "UPDATE_DECISION":
            uc_logs = GetValidationLogsUseCase(db)
            dec_dto = UpdateValidationDecisionDto(
                compliance_status=str(args.get("compliance_status") or "Lulus Verifikasi"),
                overall_score=float(args["overall_score"]) if args.get("overall_score") is not None else None,
                reviewer_notes=args.get("reviewer_notes"),
                next_action=args.get("next_action"),
            )
            updated = await uc_logs.update_decision(target_id, dec_dto, actor_id=user.id, actor_name=user.name)
            return updated.model_dump(mode="json")

        if action == "DELETE":
            await db.execute(
                delete(DocumentValidationLogModel).where(
                    (DocumentValidationLogModel.id == target_id)
                    | (DocumentValidationLogModel.document_id == target_id)
                )
            )
            await db.execute(delete(DocumentModel).where(DocumentModel.id == target_id))
            await db.commit()
            return {"deleted_id": target_id}

    # 11. SUBMIT EXTERNAL DOCUMENT ANALYSIS
    if tool_name == "prima_submit_external_document_analysis":
        now = datetime.now(timezone.utc)
        val_id = f"VAL-{uuid.uuid4().hex[:8].upper()}"
        score = float(args.get("overall_score") or 85.0)
        comp_status = str(
            args.get("compliance_status")
            or ("Lulus Verifikasi" if score >= 80 else "Perlu Perbaikan")
        )
        ext_model = str(args.get("external_model_name") or "External AI Agent (MCP)")
        summary = str(args.get("executive_summary") or "Hasil analisis dari External AI Agent.")
        recs = args.get("recommendations") if isinstance(args.get("recommendations"), list) else []
        evals = args.get("checklist_evaluations") if isinstance(args.get("checklist_evaluations"), list) else []

        log_model = DocumentValidationLogModel(
            id=val_id,
            request_id=args.get("request_id"),
            document_name=str(args.get("document_name") or "Dokumen Eksternal.pdf"),
            overall_score=score,
            passing_score_threshold=80.0,
            compliance_status=comp_status,
            processing_status="completed",
            ai_tier_requested="external",
            ai_tier_used="external",
            ai_model_used=ext_model,
            validation_result={
                "summary": summary,
                "executive_summary": summary,
                "overall_score": score,
                "compliance_status": comp_status,
                "checklist_evaluations": evals,
                "recommendations": recs,
                "extracted_project": {
                    "title": str(args.get("document_name") or "Dokumen Eksternal"),
                    "estimated_amount": 0,
                    "suggested_method": "Tender Terbuka",
                    "stages": [],
                },
            },
            validated_by_id=user.id,
            validated_by_name=f"{user.name} (via {ext_model})",
            created_at=now,
        )
        db.add(log_model)
        await db.commit()
        return {
            "validation_id": val_id,
            "document_name": log_model.document_name,
            "overall_score": score,
            "compliance_status": comp_status,
            "result_url": f"/dashboard/documents/result?id={val_id}",
        }

    # 12. USERS, NOTIFICATIONS, & SYSTEM SETTINGS
    if tool_name == "prima_manage_users_notifications_settings":
        action = str(args.get("action") or "LIST_USERS").upper()

        if action == "LIST_USERS":
            res = await db.execute(select(UserModel).where(UserModel.status == "Active"))
            users = res.scalars().all()
            return {
                "users": [
                    {"id": u.id, "name": u.name, "email": u.email, "role": u.role}
                    for u in users
                ]
            }

        if action == "LIST_NOTIFICATIONS":
            res = await db.execute(
                select(NotificationModel).order_by(desc(NotificationModel.created_at)).limit(25)
            )
            notifs = res.scalars().all()
            return {
                "notifications": [
                    {
                        "id": n.id,
                        "title": n.title,
                        "description": n.description,
                        "type": n.type,
                        "is_read": n.is_read,
                        "request_id": n.request_id,
                        "action_url": n.action_url,
                    }
                    for n in notifs
                ]
            }

        if action == "CREATE_NOTIFICATION":
            notif = NotificationModel(
                request_id=args.get("request_id"),
                title=str(args.get("title") or "Notifikasi dari External AI Agent"),
                description=str(args.get("description") or ""),
                type=str(args.get("notification_type") or "system"),
                category="Hari Ini",
                action_url=args.get("action_url"),
                is_read=False,
            )
            db.add(notif)
            await db.commit()
            await db.refresh(notif)
            return {"created_notification_id": notif.id, "title": notif.title}

        if action == "MARK_ALL_NOTIFICATIONS_READ":
            await db.execute(
                update(NotificationModel).where(NotificationModel.is_read == False).values(is_read=True)
            )
            await db.commit()
            return {"marked_all_read": True}

        if action in ("GET_SETTINGS", "UPDATE_SETTINGS"):
            res = await db.execute(select(SettingsModel).where(SettingsModel.id == "1"))
            st = res.scalar_one_or_none()
            if not st:
                st = SettingsModel(id="1")
                db.add(st)
            if action == "UPDATE_SETTINGS":
                if args.get("sla_warning_days") is not None:
                    st.sla_warning_days = int(args["sla_warning_days"])
                if args.get("auto_escalation") is not None:
                    st.auto_escalation = bool(args["auto_escalation"])
                if args.get("auto_escalate_days") is not None:
                    st.auto_escalate_days = int(args["auto_escalate_days"])
                if args.get("approval_threshold") is not None:
                    st.approval_threshold = float(args["approval_threshold"])
                await db.commit()
            return {
                "sla_warning_days": st.sla_warning_days,
                "auto_escalation": st.auto_escalation,
                "auto_escalate_days": st.auto_escalate_days,
                "approval_threshold": st.approval_threshold,
            }

    # 13. OMNI ASSISTANT NATURAL LANGUAGE ROUTER
    if tool_name == "prima_ask_or_command":
        uc = OmniAssistantUseCase(db)
        res = await uc.execute(query=str(args.get("query") or "Ringkas status PRIMA"))
        return res.model_dump(mode="json")

    # 14. GET PENDING CHAT TAKEOVER
    if tool_name == "prima_get_pending_chat_takeover":
        pending = [
            t for t in gemini_service.takeover_tickets.values() if t.get("status") == "PENDING"
        ]
        result_payload: Dict[str, Any] = {
            "pending_count": len(pending),
            "pending_tickets": pending,
        }
        if args.get("include_workspace_snapshot", True):
            uc = OmniAssistantUseCase(db)
            result_payload["workspace_snapshot"] = await uc._build_workspace_snapshot()
        return result_payload

    # 15. REPLY CHAT TAKEOVER
    if tool_name == "prima_reply_chat_takeover":
        ticket_id = str(args.get("ticket_id") or "LATEST").strip()
        answer = str(args.get("answer") or "").strip()
        if not answer:
            raise ValueError("Field 'answer' wajib diisi untuk membalas chat takeover.")
        agent_name = str(args.get("agent_name") or "External MCP Agent (Antigravity/Codex)")
        highlights = args.get("highlights") if isinstance(args.get("highlights"), list) else []
        refs = args.get("referenced_items") if isinstance(args.get("referenced_items"), list) else []
        command = args.get("command") if isinstance(args.get("command"), dict) else None
        followups = (
            args.get("suggested_followups")
            if isinstance(args.get("suggested_followups"), list)
            else []
        )
        updated_ticket = gemini_service.reply_takeover_ticket(
            ticket_id=ticket_id,
            answer=answer,
            agent_name=agent_name,
            highlights=highlights,
            referenced_items=refs,
            command=command,
            suggested_followups=followups,
        )
        return {
            "ticket_id": updated_ticket["ticket_id"],
            "status": updated_ticket["status"],
            "replied_at": updated_ticket["replied_at"],
            "agent_name": updated_ticket["agent_name"],
        }

    raise ValueError(f"Tool MCP '{tool_name}' tidak dikenal.")


@router.get("/config", summary="Get External AI & MCP Integration configuration")
async def get_integration_config(
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    cfg = await _load_synced_integration_config(db)
    recent_tickets = sorted(
        list(gemini_service.takeover_tickets.values()),
        key=lambda t: str(t.get("created_at") or ""),
        reverse=True,
    )[:15]
    return success_response(
        data={
            "config": cfg,
            "mcp_tools": MCP_TOOLS_CATALOG,
            "takeover_tickets": recent_tickets,
            "endpoints": {
                "mcp_jsonrpc_url": "/api/v1/integrations/mcp",
                "tool_execute_url": "/api/v1/integrations/tools/execute",
                "openapi_spec_url": "/openapi.json",
            },
        },
        message="Konfigurasi integrasi AI & MCP berhasil dimuat",
    )


@router.get("/takeover/tickets/{ticket_id}", summary="Poll status of an External Agent Takeover chat ticket")
async def get_takeover_ticket_status(
    ticket_id: str,
    user: UserModel = Depends(get_current_user),
):
    t = gemini_service.takeover_tickets.get(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tiket Takeover '{ticket_id}' tidak ditemukan")
    return success_response(
        data=t,
        message="Status tiket takeover berhasil dimuat",
    )


@router.put("/config", summary="Update Pluggable External AI Provider configuration")
async def update_integration_config(
    payload: AiIntegrationConfigPayload,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    await _load_synced_integration_config(db)
    update_dict = payload.model_dump()
    if update_dict.get("custom_models") is None:
        if not update_dict.get("api_key") or "..." in str(update_dict.get("api_key")):
            update_dict["api_key"] = gemini_service.external_config.get("api_key", "")

    gemini_service.set_external_config(update_dict)

    res = await db.execute(select(SettingsModel).where(SettingsModel.id == "1"))
    st = res.scalar_one_or_none()
    if not st:
        st = SettingsModel(id="1", department_reviewers={})
        db.add(st)
    rev_dict = dict(st.department_reviewers or {})
    rev_dict[_INTEGRATION_STORAGE_KEY] = json.dumps(gemini_service.external_config)
    st.department_reviewers = rev_dict
    await db.commit()

    return success_response(
        data={"config": gemini_service.get_external_config_masked()},
        message="Konfigurasi provider AI eksternal berhasil disimpan",
    )


@router.post("/token", summary="Generate a long-lived Personal Access Token for MCP / External AI Agents")
async def generate_agent_token(
    payload: GenerateTokenPayload,
    user: UserModel = Depends(get_current_user),
):
    token = create_agent_api_token(
        user_id=user.id,
        label=payload.label,
        expires_days=payload.expires_days,
    )
    return success_response(
        data={
            "token": token,
            "label": payload.label,
            "expires_days": payload.expires_days,
            "user_name": user.name,
        },
        message="Token akses AI Eksternal / MCP berhasil dibuat",
    )


@router.post("/tools/execute", summary="Directly execute any PRIMA MCP Tool (REST Playground & ChatGPT Actions)")
async def execute_mcp_tool_rest(
    payload: McpToolExecutePayload,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    await _load_synced_integration_config(db)
    try:
        output = await _execute_mcp_tool(payload.tool_name, payload.arguments, db, user)
        return success_response(
            data={"tool_name": payload.tool_name, "result": output},
            message=f"Tool '{payload.tool_name}' berhasil dijalankan",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/mcp", summary="Standard Model Context Protocol (MCP) JSON-RPC 2.0 Endpoint over HTTP")
async def mcp_jsonrpc_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    await _load_synced_integration_config(db)
    body = await request.json()
    rpc_id = body.get("id")
    method = str(body.get("method") or "")
    params = body.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "prima-pertamina-mcp-server",
                    "version": "2.0.0",
                },
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"tools": MCP_TOOLS_CATALOG},
        }

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        try:
            tool_output = await _execute_mcp_tool(tool_name, arguments, db, user)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(tool_output, ensure_ascii=False, indent=2),
                        }
                    ],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            }

    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "resources": [
                    {
                        "uri": "prima://workspace/snapshot",
                        "name": "PRIMA Live Workspace Snapshot",
                        "mimeType": "application/json",
                        "description": "Real-time snapshot of all procurements, SLAs, AI validations, documents, and guarantees.",
                    }
                ]
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": -32601, "message": f"Method '{method}' not found"},
    }
