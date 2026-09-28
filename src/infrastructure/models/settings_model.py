"""
SQLAlchemy ORM model for SystemSettings
"""
from sqlalchemy import Column, String, Float, Boolean, Integer, JSON
from src.infrastructure.database import Base


class SettingsModel(Base):
    __tablename__ = "system_settings"

    id = Column(String, primary_key=True, default="1")  # Single row
    email_notifications = Column(Boolean, default=True)
    whatsapp_notifications = Column(Boolean, default=False)
    sla_warning_days = Column(Integer, default=3)
    auto_escalation = Column(Boolean, default=False)
    auto_escalate_days = Column(Integer, default=5)
    escalation_manager_id = Column(String, default="")
    approval_threshold = Column(Float, default=100000000.0)
    department_reviewers = Column(JSON, default=dict)
    milestone_durations = Column(JSON, default=dict)
    ai_sensitivity = Column(String, default="Medium")
    theme = Column(String, default="Light")
