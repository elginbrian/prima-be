from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.infrastructure.database import get_db
from src.infrastructure.models.settings_model import SettingsModel
from src.application.dtos.settings_schemas import SystemSettingsSchema
from src.application.dtos.response_wrapper import success_response

router = APIRouter(prefix="/settings", tags=["Settings"])


async def get_or_create_settings(session: AsyncSession) -> SettingsModel:
    result = await session.execute(select(SettingsModel).where(SettingsModel.id == "1"))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = SettingsModel(id="1")
        session.add(settings)
        await session.flush()
        await session.refresh(settings)
    return settings


@router.get("", summary="Get system settings")
async def get_settings(session: AsyncSession = Depends(get_db)):
    settings = await get_or_create_settings(session)
    return success_response(
        data=SystemSettingsSchema.model_validate(settings).model_dump(),
        message="System settings retrieved"
    )


@router.put("", summary="Update system settings")
async def update_settings(
    payload: SystemSettingsSchema,
    session: AsyncSession = Depends(get_db)
):
    settings = await get_or_create_settings(session)
    
    settings.email_notifications = payload.email_notifications
    settings.whatsapp_notifications = payload.whatsapp_notifications
    settings.sla_warning_days = payload.sla_warning_days
    settings.auto_escalation = payload.auto_escalation
    settings.auto_escalate_days = payload.auto_escalate_days
    settings.escalation_manager_id = payload.escalation_manager_id
    settings.approval_threshold = payload.approval_threshold
    settings.department_reviewers = payload.department_reviewers
    settings.milestone_durations = payload.milestone_durations
    settings.ai_sensitivity = payload.ai_sensitivity
    settings.theme = payload.theme
    
    await session.flush()
    return success_response(
        data=SystemSettingsSchema.model_validate(settings).model_dump(),
        message="System settings updated"
    )
