"""
Application DTOs / Pydantic schemas for Procurement (Modul D3)
Full alignment with prima-fe types/procurement.ts
"""
from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime


class BaseUserSchema(BaseModel):
    id: str
    name: str


class DepartmentSchema(BaseModel):
    id: str
    name: str


# ─── ProcurementRequest ───────────────────────────────────────────────────────

class ProcurementRequestResponse(BaseModel):
    """Matches prima-fe ProcurementRequest type exactly (camelCase-aware via alias)"""
    id: str
    title: str
    pic: BaseUserSchema
    fpp: BaseUserSchema
    amount: float
    stage: str
    operational_status: str
    operational_status_reason: Optional[str] = None
    current_step: str
    department: DepartmentSchema
    stage_started_at: str
    is_urgent: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CreateProcurementRequest(BaseModel):
    title: str
    pic_id: str
    pic_name: str
    fpp_id: str
    fpp_name: str
    amount: float
    department_id: str
    department_name: str
    stage: str = "Persiapan"
    current_step: str = "Rapat Pra-Tender"
    is_urgent: bool = False

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Amount must be non-negative")
        return v


class UpdateOperationalStatusRequest(BaseModel):
    status: str
    reason: Optional[str] = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in ("On Going", "On Hold", "Batal"):
            raise ValueError("status must be one of: On Going, On Hold, Batal")
        return v


class MoveStepRequest(BaseModel):
    step: str

    @field_validator("step")
    @classmethod
    def valid_step(cls, v: str) -> str:
        valid_steps = [
            "Rapat Pra-Tender", "Pengumuman Pengadaan", "Prebid Meeting",
            "Pemasukan Dokumen Penawaran", "Pembukaan Penawaran",
            "Evaluasi Dokumen Penawaran", "Sosialisasi e-Auction",
            "Negosiasi e-Auction", "Negosiasi Manual",
            "Laporan Hasil Pemilihan", "Pengumuman Pemenang", "Penunjukan Pemenang",
        ]
        if v not in valid_steps:
            raise ValueError(f"step must be one of: {', '.join(valid_steps)}")
        return v


# ─── ProcurementMilestone ─────────────────────────────────────────────────────

class MilestoneResponse(BaseModel):
    id: str
    request_id: str
    step: str
    status: str
    document_id: Optional[str] = None
    date: Optional[str] = None
    pic: Optional[BaseUserSchema] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# ─── Procurement with Milestones ─────────────────────────────────────────────

class ProcurementDetailResponse(ProcurementRequestResponse):
    milestones: List[MilestoneResponse] = []
