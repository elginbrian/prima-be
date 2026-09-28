"""
Deadline entity - mirrors prima-fe types/index.ts (DeadlineItem) — Modul D4 SLA
"""
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from .user import BaseUser, Department


@dataclass
class DeadlineItem:
    id: str
    request_id: str
    task_name: str
    milestone: str
    pic: BaseUser
    department: str         # Department
    target_date: datetime
    status: str             # "On Track" | "At Risk" | "Overdue" | "Selesai"
    urgency_level: str      # "Low" | "Medium" | "High" | "Critical"
    start_date: Optional[datetime] = None
    next_action: Optional[str] = None
    overdue_reason: Optional[str] = None
    paused_at: Optional[datetime] = None
    accumulated_paused_days: int = 0
