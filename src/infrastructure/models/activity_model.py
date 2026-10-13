import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from src.infrastructure.database import Base


class ProcurementActivityLogModel(Base):
    __tablename__ = "procurement_activity_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String, ForeignKey("procurement_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, nullable=True)
    user_name = Column(String, nullable=True)
    action = Column(String(50), nullable=False)  # CREATE, MOVE_STAGE, MOVE_STEP, UPDATE_STATUS, UPDATE_SLA
    previous_state = Column(String(100), nullable=True)
    new_state = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    request = relationship("ProcurementRequestModel", backref="activity_logs")
