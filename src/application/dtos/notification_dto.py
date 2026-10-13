from pydantic import BaseModel, ConfigDict, model_validator
from typing import Optional
from datetime import datetime

class NotificationCreateDto(BaseModel):
    request_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    message: Optional[str] = None
    type: str = "System"
    category: str = "Pengadaan"

    @model_validator(mode="after")
    def populate_description(self):
        if not self.description:
            self.description = self.message or ""
        return self

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
