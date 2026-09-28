"""
SQLAlchemy ORM model for ProcurementRequest and ProcurementMilestone (Modul D3)
"""
from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from src.infrastructure.database import Base


class ProcurementRequestModel(Base):
    __tablename__ = "procurement_requests"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)

    # PIC (Person In Charge) — stored as flat fields for simplicity
    pic_id = Column(String, nullable=False)
    pic_name = Column(String, nullable=False)

    # FPP (Fungsi Permintaan Pengadaan)
    fpp_id = Column(String, nullable=False)
    fpp_name = Column(String, nullable=False)

    amount = Column(Float, nullable=False, default=0)

    # Stage: Persiapan | Sourcing | Evaluasi | Contracting | Selesai
    stage = Column(String, nullable=False, default="Persiapan")

    # Operational status: On Going | On Hold | Batal
    operational_status = Column(String, nullable=False, default="On Going")
    operational_status_reason = Column(Text, nullable=True)

    # Current step within stage
    current_step = Column(String, nullable=False, default="Rapat Pra-Tender")

    # Department — stored as flat fields
    department_id = Column(String, nullable=False)
    department_name = Column(String, nullable=False)

    is_urgent = Column(Boolean, default=False)

    stage_started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    milestones = relationship("ProcurementMilestoneModel", back_populates="request", cascade="all, delete-orphan")


class ProcurementMilestoneModel(Base):
    __tablename__ = "procurement_milestones"

    id = Column(String, primary_key=True, index=True)
    request_id = Column(String, ForeignKey("procurement_requests.id", ondelete="CASCADE"), nullable=False, index=True)

    step = Column(String, nullable=False)
    status = Column(String, nullable=False, default="Pending")  # Pending | In Progress | Done | Skipped

    document_id = Column(String, nullable=True)
    date = Column(DateTime(timezone=True), nullable=True)
    pic_id = Column(String, nullable=True)
    pic_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    # Relationships
    request = relationship("ProcurementRequestModel", back_populates="milestones")
