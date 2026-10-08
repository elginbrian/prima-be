from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from src.infrastructure.database import Base


class GuaranteeModel(Base):
    __tablename__ = "guarantees"

    id = Column(String, primary_key=True, index=True)
    request_id = Column(String, ForeignKey("procurement_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    
    reference_no = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False) # e.g., "Pelaksanaan", "Uang Muka", "Pemeliharaan"
    value = Column(Float, nullable=False, default=0)
    
    issuer = Column(String, nullable=False)
    issuer_type = Column(String, nullable=True) # e.g., "Bank", "Asuransi"
    beneficiary = Column(String, nullable=True)
    
    # Vendor - flat fields
    vendor_id = Column(String, nullable=False)
    vendor_name = Column(String, nullable=False)
    
    issue_date = Column(DateTime(timezone=True), nullable=False)
    expiry_date = Column(DateTime(timezone=True), nullable=False)
    
    # PIC - flat fields
    pic_id = Column(String, nullable=False)
    pic_name = Column(String, nullable=False)
    
    status = Column(String, nullable=False, default="Active") # Active, Expired, Claimed, Returned
    next_action = Column(String, nullable=True)
    
    # File storage
    file_url = Column(Text, nullable=True) # Store object key or full URL

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    request = relationship("ProcurementRequestModel")
