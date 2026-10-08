from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class DocumentCreateDto(BaseModel):
    request_id: UUID
    name: str
    type: str
    document_kind: Optional[str] = None
    status: str
    pic_id: str
    pic_name: str
    issues: Optional[List[str]] = []
    next_action: Optional[str] = None
    procurement_step: Optional[str] = None
    document_date: Optional[str] = None
    document_number: Optional[str] = None
    file_url: Optional[str] = None
    mime_type: Optional[str] = None

class DocumentUpdateDto(BaseModel):
    status: Optional[str] = None
    issues: Optional[List[str]] = None
    next_action: Optional[str] = None

class DocumentResponseDto(BaseModel):
    id: UUID
    request_id: UUID
    name: str
    type: str
    document_kind: Optional[str]
    status: str
    upload_date: datetime
    pic_id: str
    pic_name: str
    issues: List[str]
    next_action: Optional[str]
    procurement_step: Optional[str]
    document_date: Optional[str]
    document_number: Optional[str]
    file_url: Optional[str]
    mime_type: Optional[str]

    model_config = ConfigDict(from_attributes=True)
