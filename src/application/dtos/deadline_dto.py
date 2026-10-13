from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from src.application.dtos.procurement_schemas import BaseUserSchema, DepartmentSchema

class DeadlineCreateDto(BaseModel):
    request_id: str
    task_name: str
    milestone: str
    pic_id: str
    pic_name: str
    department_id: str
    department_name: str
    target_date: datetime
    start_date: Optional[datetime] = None
    status: str = "On Track"
    urgency_level: str = "Medium"
    next_action: Optional[str] = None
    overdue_reason: Optional[str] = None
    is_escalated: bool = False
    escalated_at: Optional[datetime] = None
    escalated_to: Optional[str] = None
    recovery_date: Optional[datetime] = None
    recovery_plan: Optional[str] = None

class DeadlineUpdateDto(BaseModel):
    task_name: Optional[str] = None
    milestone: Optional[str] = None
    pic_id: Optional[str] = None
    pic_name: Optional[str] = None
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    target_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    status: Optional[str] = None
    urgency_level: Optional[str] = None
    next_action: Optional[str] = None
    overdue_reason: Optional[str] = None
    is_escalated: Optional[bool] = None
    escalated_at: Optional[datetime] = None
    escalated_to: Optional[str] = None
    recovery_date: Optional[datetime] = None
    recovery_plan: Optional[str] = None

class EscalateDeadlineDto(BaseModel):
    escalated_to: Optional[str] = None
    reason: Optional[str] = None

class RecoveryPlanDto(BaseModel):
    recovery_plan: str
    recovery_date: datetime

class DeadlineResponseDto(DeadlineCreateDto):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
