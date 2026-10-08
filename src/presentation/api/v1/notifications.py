from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, select, update
from typing import List

from src.infrastructure.database import get_db
from src.infrastructure.models.notification_model import NotificationModel
from src.application.dtos.notification_dto import NotificationResponseDto, NotificationCreateDto
from src.application.dtos.response_wrapper import success_response

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/", response_model=dict)
async def get_notifications(db: AsyncSession = Depends(get_db)):
    """Fetch all notifications ordered by newest first."""
    result = await db.execute(select(NotificationModel).order_by(desc(NotificationModel.created_at)))
    notifs = result.scalars().all()
    dto_list = [NotificationResponseDto.model_validate(n).model_dump() for n in notifs]
    return success_response(data=dto_list, message="Notifications fetched")

@router.post("/", response_model=dict)
async def create_notification(payload: NotificationCreateDto, db: AsyncSession = Depends(get_db)):
    """Create a new notification."""
    notif = NotificationModel(**payload.model_dump())
    db.add(notif)
    await db.commit()
    await db.refresh(notif)
    return success_response(data=NotificationResponseDto.model_validate(notif).model_dump(), message="Notification created")

@router.put("/{notification_id}/read", response_model=dict)
async def mark_notification_read(notification_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a notification as read."""
    result = await db.execute(select(NotificationModel).where(NotificationModel.id == notification_id))
    notif = result.scalars().first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return success_response(data=NotificationResponseDto.model_validate(notif).model_dump(), message="Notification marked as read")

@router.put("/read-all", response_model=dict)
async def mark_all_notifications_read(db: AsyncSession = Depends(get_db)):
    """Mark all notifications as read."""
    await db.execute(update(NotificationModel).where(NotificationModel.is_read == False).values(is_read=True))
    await db.commit()
    return success_response(data=None, message="All notifications marked as read")
