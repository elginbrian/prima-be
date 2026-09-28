"""
Guarantee entity - matches prima-fe types/guarantee.ts exactly

Key difference from earlier scaffold:
- `vendor: BaseUser` (not issuing_bank string)
- `referenceNo: str` (not just name)
- `issuer: str`, `issuerType?: "Bank" | "Asuransi" | "Lainnya"`
- `beneficiary?: str`
- `submissionDate?: str`
- GuaranteeType: "Jaminan Pelaksanaan" | "Jaminan Masa Pemeliharaan" | "Jaminan Uang Muka"
"""
from dataclasses import dataclass
from typing import Optional
from .user import BaseUser


@dataclass
class GuaranteeItem:
    id: str
    request_id: str
    reference_no: str
    type: str               # GuaranteeType
    value: float
    issuer: str
    vendor: BaseUser        # The vendor entity (BaseUser)
    issue_date: str         # ISO date string
    expiry_date: str        # ISO date string
    pic: BaseUser
    status: str             # "Aktif" | "Mendekati Expiry" | "Expired"
    issuer_type: Optional[str] = None   # "Bank" | "Asuransi" | "Lainnya"
    beneficiary: Optional[str] = None
    submission_date: Optional[str] = None
    next_action: Optional[str] = None
    file_url: Optional[str] = None
    mime_type: Optional[str] = None


GUARANTEE_TYPES = ["Jaminan Pelaksanaan", "Jaminan Masa Pemeliharaan", "Jaminan Uang Muka"]
GUARANTEE_ISSUER_TYPES = ["Bank", "Asuransi", "Lainnya"]
GUARANTEE_STATUSES = ["Aktif", "Mendekati Expiry", "Expired"]
