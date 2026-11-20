"""
SQLAlchemy ORM model for configurable Procurement Workflow Stages (Admin Managed)
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text

from src.infrastructure.database import Base


class WorkflowStageModel(Base):
    """
    Master table for configurable procurement workflow steps/stages per method.
    Allows Admin to add, edit, reorder, and deactivate stages dynamically.
    """
    __tablename__ = "workflow_stages"

    id = Column(String(50), primary_key=True, default=lambda: f"STG-{uuid.uuid4().hex[:8].upper()}", index=True)
    procurement_method = Column(String(100), nullable=False, default="Tender Terbuka", index=True)
    step_name = Column(String(200), nullable=False)
    stage_group = Column(String(50), nullable=False, default="Sourcing")  # Persiapan | Sourcing | Evaluasi | Contracting | Selesai
    order_index = Column(Integer, nullable=False, default=0)
    default_sla_days = Column(Integer, nullable=True, default=5)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
