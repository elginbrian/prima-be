import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship

from src.infrastructure.database import Base

class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String, ForeignKey("procurement_requests.id"), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(String(100), nullable=False)
    document_kind = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False)
    upload_date = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    pic_id = Column(String(50), nullable=False)
    pic_name = Column(String(150), nullable=False)
    issues = Column(ARRAY(String), default=list)
    next_action = Column(String, nullable=True)
    procurement_step = Column(String(100), nullable=True)
    document_date = Column(String(50), nullable=True)
    document_number = Column(String(100), nullable=True)
    file_url = Column(String, nullable=True)
    mime_type = Column(String(100), nullable=True)

    request = relationship("ProcurementRequestModel", backref="documents")
