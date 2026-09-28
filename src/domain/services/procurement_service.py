"""
Procurement domain service — business logic that doesn't belong to one entity alone.
Mirrors the derived-action logic in prima-fe ProcurementContext.tsx
"""
from typing import List
from datetime import datetime, date
from src.domain.entities.guarantee import GuaranteeItem
from src.domain.entities.deadline import DeadlineItem
from src.domain.entities.document import DocumentItem


class ProcurementDomainService:
    """Business rules for the procurement system"""

    @staticmethod
    def compute_guarantee_status(guarantee: GuaranteeItem) -> str:
        """Compute status from expiry_date (mirrors FE logic)"""
        today = date.today()
        days_left = (guarantee.expiry_date - today).days
        if days_left < 0:
            return "Expired"
        elif days_left <= 30:
            return "Mendekati Expiry"
        return "Aktif"

    @staticmethod
    def compute_deadline_urgency(deadline: DeadlineItem) -> str:
        """Compute urgency level from target_date"""
        now = datetime.utcnow()
        days_left = (deadline.target_date - now).days
        if days_left < 0:
            return "Critical"
        elif days_left <= 3:
            return "High"
        elif days_left <= 7:
            return "Medium"
        return "Low"

    @staticmethod
    def get_urgent_documents(documents: List[DocumentItem]) -> List[DocumentItem]:
        """Return documents that need immediate attention"""
        return [
            doc for doc in documents
            if doc.status in ("Catatan Procurement", "Tindak Lanjut FPP")
        ]
