"""
Document entity - mirrors prima-fe types/procurement.ts (DocumentItem)
"""
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime
from .user import BaseUser


@dataclass
class DocumentItem:
    id: str
    request_id: str
    name: str
    type: str           # "Wajib" | "Kondisional" | "Best Practice" | "Dokumentasi"
    status: str         # "Lulus Verifikasi" | "Catatan Procurement" | "Tindak Lanjut FPP"
    upload_date: datetime
    pic: BaseUser
    issues: List[str] = field(default_factory=list)
    document_kind: Optional[str] = None
    next_action: Optional[str] = None
    procurement_step: Optional[str] = None
    document_date: Optional[datetime] = None
    document_number: Optional[str] = None
    can_generate_ai_draft: bool = False
    file_url: Optional[str] = None
    mime_type: Optional[str] = None
