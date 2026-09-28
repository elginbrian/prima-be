"""
Guarantee entity - mirrors prima-fe types/guarantee.ts
"""
from dataclasses import dataclass
from typing import Optional
from datetime import date
from .user import BaseUser


@dataclass
class GuaranteeItem:
    id: str
    request_id: str
    name: str
    type: str           # "Bank Guarantee" | "Surety Bond" | "Asuransi" | "Lainnya"
    value: float
    issuing_bank: str
    issue_date: date
    expiry_date: date
    status: str         # "Aktif" | "Mendekati Expiry" | "Expired"
    pic: BaseUser
    notes: Optional[str] = None
