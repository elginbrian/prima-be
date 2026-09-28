"""
Settings DTOs
"""
from pydantic import BaseModel
from typing import Dict


class SystemSettingsSchema(BaseModel):
    email_notifications: bool = True
    whatsapp_notifications: bool = False
    sla_warning_days: int = 3
    auto_escalation: bool = False
    auto_escalate_days: int = 5
    escalation_manager_id: str = ""
    approval_threshold: float = 100000000.0
    department_reviewers: Dict[str, str] = {}
    milestone_durations: Dict[str, int] = {}
    ai_sensitivity: str = "Medium"
    theme: str = "Light"

    class Config:
        from_attributes = True
