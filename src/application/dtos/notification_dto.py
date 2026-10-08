from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

class NotificationCreateDto(BaseModel):
    request_id: Optional[UUID] = None
    title: str
    description: str
    type: str
    category: str

class NotificationResponseDto(BaseModel):
    id: UUID
    request_id: Optional[UUID]
    title: str
    description: str
    is_read: bool
    type: str
    category: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
