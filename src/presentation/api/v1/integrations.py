"""
PRIMA External AI Integration & Model Context Protocol (MCP) Server Router
- Exposes JSON-RPC 2.0 MCP endpoint (/api/v1/integrations/mcp) with full CRUD & analysis tools
- Manages Pluggable External AI Provider configuration (stored in system_settings.milestone_durations['_ai_integration'])
- Generates long-lived Personal Access Tokens (PAT) for Antigravity, Codex, Claude Code, Cursor, and ChatGPT Actions
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import get_db
from src.infrastructure.models.settings_model import SettingsModel
from src.infrastructure.models.user_model import UserModel
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.validation_model import DocumentValidationLogModel
from src.infrastructure.models.workflow_stage_model import WorkflowStageModel
from src.infrastructure.ai.gemini_service import gemini_service
from src.infrastructure.security.jwt import create_agent_api_token
from src.presentation.auth_dependencies import get_current_user
from src.application.dtos.response_wrapper import success_response
from src.application.use_cases.omni_assistant_use_case import OmniAssistantUseCase
from src.application.use_cases.procurement_use_cases import (
    CreateProcurementUseCase,
    MoveStageUseCase,
    MoveStepUseCase,
    UpdateOperationalStatusUseCase,
)
from src.infrastructure.repositories.procurement_repository import PostgresProcurementRepository

router = APIRouter(prefix="/integrations", tags=["External AI & MCP Integrations"])

_INTEGRATION_STORAGE_KEY = "__ai_integration_config__"


class AiIntegrationConfigPayload(BaseModel):
    provider_mode: str = Field(
        default="internal_gemini",
        description="internal_gemini | openai_compatible | custom_webhook | mcp_takeover",
    )
    provider_name: str = Field(default="PRIMA Internal (Google Gemini)")
    base_url: str = Field(default="https://api.openai.com/v1")
    api_key: Optional[str] = Field(default=None)
    model_name: str = Field(default="gpt-4o-mini")
    replace_chat_brain: bool = Field(default=True)
    replace_analysis_brain: bool = Field(default=False)


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
                "request_id": {"type": "string", "description": "ID Pekerjaan (mis. REQ-001)"},
                "new_stage": {"type": "string", "description": "Opsional: Persiapan | Sourcing | Evaluasi | Contracting | Selesai"},
                "new_step": {"type": "string", "description": "Opsional: Nama langkah spesifik"},
                "operational_status": {"type": "string", "description": "Opsional: On Going | On Hold | Batal"},
                "notes": {"type": "string", "description": "Catatan atau alasan perubahan"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "prima_manage_sla_deadline",
        "description": "Menandai SLA selesai, melakukan eskalasi SLA ke manajer, atau menyimpan rencana mitigasi (recovery plan).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "deadline_id": {"type": "string", "description": "ID SLA / Deadline (mis. D-...)"},
                "action": {"type": "string", "enum": ["COMPLETE", "ESCALATE", "RECOVERY_PLAN"]},
                "escalated_to": {"type": "string", "description": "Tujuan eskalasi manajerial"},
                "reason_or_plan": {"type": "string", "description": "Alasan eskalasi atau rencana mitigasi"},
            },
            "required": ["deadline_id", "action"],
        },
    },
    {
        "name": "prima_create_custom_method",
        "description": "Membuat metode pengadaan custom baru beserta urutan tahapan dan standar SLA hariannya.",
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
            },
            "required": ["document_name", "overall_score", "executive_summary"],
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
    if tool_name == "prima_get_workspace_snapshot":
        uc = OmniAssistantUseCase(db)
        snapshot = await uc._build_workspace_snapshot()
        return snapshot

    if tool_name == "prima_create_procurement":
        repo = PostgresProcurementRepository(db)
        uc = CreateProcurementUseCase(repo)
        created = await uc.execute(
            title=str(args.get("title") or "Pekerjaan Baru via External AI"),
            pic_id=user.id,
            pic_name=user.name,
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
        }

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

    if tool_name == "prima_manage_sla_deadline":
        dl_id = str(args.get("deadline_id") or "").strip()
        action = str(args.get("action") or "COMPLETE").upper()
        res = await db.execute(select(DeadlineModel).where(DeadlineModel.id == dl_id))
        dl = res.scalar_one_or_none()
        if not dl:
            raise ValueError(f"Deadline '{dl_id}' tidak ditemukan")

        now = datetime.now(timezone.utc)
        if action == "COMPLETE":
            dl.status = "Selesai"
        elif action == "ESCALATE":
            dl.is_escalated = True
            dl.escalated_at = now
            dl.escalated_to = str(args.get("escalated_to") or "Manager Pengadaan Korporat")
            dl.overdue_reason = str(args.get("reason_or_plan") or "Dieskalasi oleh External AI Agent")
        elif action == "RECOVERY_PLAN":
            dl.recovery_plan = str(args.get("reason_or_plan") or "Percepatan tahapan via External AI Agent")
            dl.recovery_date = now
        dl.updated_at = now
        await db.commit()
        return {
            "deadline_id": dl.id,
            "task_name": dl.task_name,
            "status": dl.status,
            "is_escalated": dl.is_escalated,
            "recovery_plan": dl.recovery_plan,
        }

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
                "checklist_evaluations": [],
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

    if tool_name == "prima_ask_or_command":
        uc = OmniAssistantUseCase(db)
        res = await uc.execute(query=str(args.get("query") or "Ringkas status PRIMA"))
        return res.model_dump(mode="json")

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

    if tool_name == "prima_reply_chat_takeover":
        ticket_id = str(args.get("ticket_id") or "LATEST").strip()
        answer = str(args.get("answer") or "").strip()
        if not answer:
            raise ValueError("Field 'answer' wajib diisi untuk membalas chat takeover.")
        agent_name = str(args.get("agent_name") or "External MCP Agent (Antigravity/Codex)")
        highlights = args.get("highlights") if isinstance(args.get("highlights"), list) else []
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
    # Keep existing API key if user sent masked or empty string when updating other fields
    if not update_dict.get("api_key") or "..." in str(update_dict.get("api_key")):
        update_dict["api_key"] = gemini_service.external_config.get("api_key", "")

    gemini_service.set_external_config(update_dict)

    # Persist in SettingsModel JSON column so it survives restarts without requiring schema migration
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
    """
    Implements the Model Context Protocol (MCP) JSON-RPC 2.0 specification over Streamable HTTP:
    Supports:
    - initialize
    - tools/list
    - tools/call
    - resources/list
    - ping
    """
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
                    "version": "1.0.0",
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
