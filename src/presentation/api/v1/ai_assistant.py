import json
from typing import List
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import get_db
from src.application.dtos.response_wrapper import success_response
from src.application.dtos.omni_assistant_dto import OmniChatHistoryTurnDto
from src.application.use_cases.omni_assistant_use_case import OmniAssistantUseCase

router = APIRouter(prefix="/ai", tags=["Omni-Search Generative AI"])


@router.post("/omni-assistant", summary="Omni-Search Generative AI Q&A and Action Command Router (Cekatan mode + Optional 1 Attachment)")
async def query_omni_assistant(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Processes natural language questions, commands, and an optional single file attachment
    from the /dashboard/onboarding Omni-Search bar, Diskusi AI page, or Global AI Sidebar.
    Supports both application/json and multipart/form-data.
    Strictly runs in 'cekatan' AI tier for low-latency responses with automatic failover.
    """
    content_type = (request.headers.get("content-type") or "").lower()
    query_str = ""
    page_context_str = ""
    ai_tier_str: str | None = None
    custom_model_id_str: str | None = None
    history_turns: List[OmniChatHistoryTurnDto] = []
    attachment_bytes: bytes | None = None
    attachment_mime: str | None = None
    attachment_filename: str | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        query_str = str(form.get("query") or "").strip()
        page_context_str = str(form.get("page_context") or "").strip()
        ai_tier_raw = form.get("ai_tier")
        ai_tier_str = str(ai_tier_raw).strip() if ai_tier_raw else None
        custom_id_raw = form.get("custom_model_id")
        custom_model_id_str = str(custom_id_raw).strip() if custom_id_raw else None
        raw_history = form.get("history")
        if raw_history and isinstance(raw_history, str):
            try:
                parsed_hist = json.loads(raw_history)
                if isinstance(parsed_hist, list):
                    history_turns = [
                        OmniChatHistoryTurnDto.model_validate(item)
                        for item in parsed_hist
                        if isinstance(item, dict)
                    ]
            except Exception:
                history_turns = []

        upload_file = form.get("file")
        if upload_file and hasattr(upload_file, "read"):
            attachment_bytes = await upload_file.read()  # type: ignore[misc]
            attachment_filename = getattr(upload_file, "filename", None) or "lampiran"
            attachment_mime = getattr(upload_file, "content_type", None) or "application/octet-stream"
    else:
        body = await request.json()
        query_str = str(body.get("query") or "").strip()
        page_context_str = str(body.get("page_context") or "").strip()
        ai_tier_raw = body.get("ai_tier")
        ai_tier_str = str(ai_tier_raw).strip() if ai_tier_raw else None
        custom_id_raw = body.get("custom_model_id")
        custom_model_id_str = str(custom_id_raw).strip() if custom_id_raw else None
        raw_history = body.get("history") or []
        if isinstance(raw_history, list):
            history_turns = [
                OmniChatHistoryTurnDto.model_validate(item)
                for item in raw_history
                if isinstance(item, dict)
            ]

    if not query_str and attachment_filename:
        query_str = f"Tolong analisis dan ringkas isi berkas lampiran '{attachment_filename}' ini."

    if len(query_str) < 2:
        raise HTTPException(status_code=422, detail="Pertanyaan atau perintah terlalu pendek.")

    uc = OmniAssistantUseCase(db)
    result = await uc.execute(
        query=query_str,
        history=history_turns,
        attachment_bytes=attachment_bytes,
        attachment_mime=attachment_mime,
        attachment_filename=attachment_filename,
        page_context=page_context_str or None,
        ai_tier=ai_tier_str,
        custom_model_id=custom_model_id_str,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Respons AI Omni-Assistant berhasil dibuat",
    )
