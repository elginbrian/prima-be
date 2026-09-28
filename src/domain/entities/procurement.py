"""
Procurement entities - mirrors prima-fe types/procurement.ts
"""
from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum
from datetime import datetime
from .user import BaseUser, Department


ProcurementStage = Literal["Persiapan", "Sourcing", "Evaluasi", "Contracting", "Selesai"]
ProcurementOperationalStatus = Literal["On Going", "On Hold", "Batal"]
ProcurementStep = Literal[
    "Rapat Pra-Tender",
    "Pengumuman Pengadaan",
    "Prebid Meeting",
    "Pemasukan Dokumen Penawaran",
    "Pembukaan Penawaran",
    "Evaluasi Dokumen Penawaran",
    "Sosialisasi e-Auction",
    "Negosiasi e-Auction",
    "Negosiasi Manual",
    "Laporan Hasil Pemilihan",
    "Pengumuman Pemenang",
    "Penunjukan Pemenang",
]
ProcurementMilestoneStatus = Literal["Pending", "In Progress", "Done", "Skipped"]


@dataclass
class ProcurementMilestone:
    id: str
    request_id: str
    step: str  # ProcurementStep
    status: str  # ProcurementMilestoneStatus
    document_id: Optional[str] = None
    date: Optional[datetime] = None
    pic: Optional[BaseUser] = None
    notes: Optional[str] = None


@dataclass
class ProcurementRequest:
    id: str
    title: str
    pic: BaseUser
    fpp: BaseUser
    amount: float
    stage: str           # ProcurementStage
    operational_status: str  # ProcurementOperationalStatus
    current_step: str    # ProcurementStep
    department: str      # Department
    stage_started_at: datetime
    created_at: datetime
    updated_at: datetime
    operational_status_reason: Optional[str] = None
    is_urgent: bool = False
