from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List

from src.infrastructure.database import get_db
from src.infrastructure.models.notification_model import NotificationModel
from src.application.dtos.notification_dto import NotificationResponseDto, NotificationCreateDto

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/", response_model=List[NotificationResponseDto])
def get_notifications(db: Session = Depends(get_db)):
    """Fetch all notifications ordered by newest first."""
    notifications = db.query(NotificationModel).order_by(desc(NotificationModel.created_at)).all()
    return notifications

@router.post("/", response_model=NotificationResponseDto)
def create_notification(payload: NotificationCreateDto, db: Session = Depends(get_db)):
    """Create a new notification."""
    notif = NotificationModel(**payload.model_dump())
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif

@router.put("/{notification_id}/read", response_model=NotificationResponseDto)
def mark_notification_read(notification_id: str, db: Session = Depends(get_db)):
    """Mark a notification as read."""
    notif = db.query(NotificationModel).filter(NotificationModel.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif

@router.put("/read-all", response_model=dict)
def mark_all_notifications_read(db: Session = Depends(get_db)):
    """Mark all notifications as read."""
    db.query(NotificationModel).filter(NotificationModel.is_read == False).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read"}
