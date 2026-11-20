from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import get_db
from src.application.dtos.response_wrapper import success_response
from src.application.dtos.omni_assistant_dto import OmniAssistantQueryRequest
from src.application.use_cases.omni_assistant_use_case import OmniAssistantUseCase

router = APIRouter(prefix="/ai", tags=["Omni-Search Generative AI"])


@router.post("/omni-assistant", summary="Omni-Search Generative AI Q&A and Action Command Router (Cekatan mode)")
async def query_omni_assistant(
    payload: OmniAssistantQueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Processes natural language questions and commands from the /dashboard/onboarding Omni-Search bar.
    Strictly runs in 'cekatan' AI tier for low-latency responses with automatic failover.
    """
    uc = OmniAssistantUseCase(db)
    result = await uc.execute(payload.query, history=payload.history)
    return success_response(
        data=result.model_dump(mode="json"),
        message="Respons AI Omni-Assistant berhasil dibuat",
    )
