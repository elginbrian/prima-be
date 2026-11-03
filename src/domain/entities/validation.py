"""
Validation Entity (Modul D1 & Audit Trail D2/D3/D4)

Represents a checklist evaluation of any procurement document, including
itemized results, evidence quotes, document score, and workflow stages.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class ChecklistItemResult:
    item: str
    status: str  # "Memenuhi" | "Tidak Memenuhi" | "Perlu Perhatian"
    evidence_quote: Optional[str] = None
    explanation: Optional[str] = None
    severity: str = "SUCCESS"  # "SUCCESS" | "WARNING" | "ERROR"


@dataclass
class ExtractedStage:
    step: str
    status: str = "Pending"  # "Done" | "In Progress" | "Pending"
    auto_cleared: bool = False
    notes: Optional[str] = None


@dataclass
class ExtractedProject:
    title: str
    estimated_amount: float = 0.0
    suggested_method: str = "Tender Terbuka"
    department_name: str = "Procurement & General Support"
    stages: List[ExtractedStage] = field(default_factory=list)


@dataclass
class DocumentValidationLog:
    id: str
    document_name: str
    checklist_snapshot: List[str]
    validation_result: Dict[str, Any]
    overall_score: float
    compliance_status: str
    created_at: datetime
    request_id: Optional[str] = None
    document_id: Optional[str] = None
    document_file_url: Optional[str] = None
    mime_type: Optional[str] = None
    user_prompt: Optional[str] = None
    validated_by_id: Optional[str] = None
    validated_by_name: Optional[str] = None

