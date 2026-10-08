import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.infrastructure.database import Base

class NotificationModel(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("procurement_requests.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    type = Column(String(50), nullable=False) # success, alert, system, document, deadline
    category = Column(String(50), nullable=False) # Hari Ini, Kemarin, Lebih Lama
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    request = relationship("ProcurementRequestModel", backref="notifications")
