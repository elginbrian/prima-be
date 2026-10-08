from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class NotificationCreateDto(BaseModel):
    request_id: Optional[str] = None
    title: str
    description: str
    type: str
    category: str

class NotificationResponseDto(BaseModel):
    id: str
    request_id: Optional[str]
    title: str
    description: str
    is_read: bool
    type: str
    category: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
