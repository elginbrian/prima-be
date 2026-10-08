from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from src.infrastructure.database import Base

class DeadlineModel(Base):
    __tablename__ = "deadlines"

    id = Column(String(50), primary_key=True, index=True)
    request_id = Column(String(50), ForeignKey("procurement_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    
    task_name = Column(String(255), nullable=False)
    milestone = Column(String(100), nullable=False)
    
    pic_id = Column(String(50), nullable=False)
    pic_name = Column(String(100), nullable=False)
    
    department_id = Column(String(50), nullable=False)
    department_name = Column(String(100), nullable=False)
    
    target_date = Column(DateTime(timezone=True), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=True)
    
    status = Column(String(50), nullable=False, default="On Track")
    urgency_level = Column(String(50), nullable=False, default="Medium")
    
    next_action = Column(Text, nullable=True)
    overdue_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    request = relationship("ProcurementRequestModel")
