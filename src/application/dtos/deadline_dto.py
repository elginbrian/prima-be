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

class DeadlineResponseDto(BaseModel):
    id: str
    request_id: str
    task_name: str
    milestone: str
    pic: BaseUserSchema
    department: DepartmentSchema
    target_date: datetime
    start_date: Optional[datetime] = None
    status: str
    urgency_level: str
    next_action: Optional[str] = None
    overdue_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm(cls, obj):
        return cls(
            id=obj.id,
            request_id=obj.request_id,
            task_name=obj.task_name,
            milestone=obj.milestone,
            pic=BaseUserSchema(id=obj.pic_id, name=obj.pic_name),
            department=DepartmentSchema(id=obj.department_id, name=obj.department_name),
            target_date=obj.target_date,
            start_date=obj.start_date,
            status=obj.status,
            urgency_level=obj.urgency_level,
            next_action=obj.next_action,
            overdue_reason=obj.overdue_reason,
            created_at=obj.created_at,
            updated_at=obj.updated_at
        )

    model_config = ConfigDict(from_attributes=True)
