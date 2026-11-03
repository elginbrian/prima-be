"""
SQLAlchemy ORM model for Document Validation Logs (Modul D1 & Audit Trail D2/D3/D4)

Stores immutable snapshots of checklist validations, AI evaluations, scores,
recommendations, and extracted workflow milestones.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship

from src.infrastructure.database import Base


class ValidationProfileModel(Base):
    """
    Validation Profile / Evaluation Schema Template
    Allows user/admin to create, name, configure, and reuse modular document validation rules.
    """
    __tablename__ = "validation_profiles"

    id = Column(String(50), primary_key=True, default=lambda: f"VPROF-{uuid.uuid4().hex[:8].upper()}", index=True)
    name = Column(String(255), nullable=False, index=True)
    code = Column(String(100), nullable=True, unique=True, index=True)
    document_kind = Column(String(100), nullable=False, default="Umum", index=True)
    description = Column(Text, nullable=True)

    # Governance scope
    scope = Column(String(50), nullable=False, default="GLOBAL")  # GLOBAL | IT | INFRASTRUCTURE | SERVICES
    department_id = Column(String(50), nullable=True)
    department_name = Column(String(150), nullable=True)

    # Scoring & Thresholds
    passing_score_threshold = Column(Float, nullable=False, default=80.0)
    warning_score_threshold = Column(Float, nullable=False, default=60.0)
    strict_mandatory_enforcement = Column(Boolean, nullable=False, default=True)

    # Workflow Linkage (Tahapan tracker yang otomatis di-clear jika dokumen lolos)
    target_stage_to_clear = Column(String(150), nullable=True)

    # AI Guidance
    custom_system_prompt = Column(Text, nullable=True)

    # Structured checklist rules: list of {category, item, guidance, is_mandatory, weight, severity_on_failure}
    checklist_rules = Column(JSON, nullable=False, default=list)

    # State & Metadata
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by_id = Column(String(50), nullable=True)
    created_by_name = Column(String(150), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class DocumentValidationLogModel(Base):
    __tablename__ = "document_validation_logs"

    id = Column(String(50), primary_key=True, default=lambda: f"VAL-{uuid.uuid4().hex[:8].upper()}", index=True)
    
    # Linked procurement request (nullable until published into Tracker)
    request_id = Column(String(50), ForeignKey("procurement_requests.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Linked document record (if published/registered)
    document_id = Column(String(50), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Linked validation profile / template (audit trail of which criteria was used)
    profile_id = Column(String(50), ForeignKey("validation_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    profile_name = Column(String(255), nullable=True)

    # Document Metadata
    document_name = Column(String(255), nullable=False)
    document_file_url = Column(Text, nullable=True)
    mime_type = Column(String(100), nullable=True)
    
    # User inputs
    user_prompt = Column(Text, nullable=True)
    checklist_snapshot = Column(JSON, nullable=False, default=list)
    
    # AI Evaluation Results (JSON object containing evaluations, evidence, recommendations, and extracted stages)
    validation_result = Column(JSON, nullable=False, default=dict)
    
    # Scoring & Status
    overall_score = Column(Float, nullable=False, default=0.0)
    passing_score_threshold = Column(Float, nullable=True, default=80.0)
    compliance_status = Column(String(50), nullable=False, default="Catatan Procurement")
    
    # Auditor / Uploader Information
    validated_by_id = Column(String(50), nullable=True)
    validated_by_name = Column(String(150), nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    request = relationship("ProcurementRequestModel", backref="validation_logs")
    document = relationship("DocumentModel", backref="validation_logs")
    profile = relationship("ValidationProfileModel", backref="validation_logs")

