from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class GuaranteeCreateDto(BaseModel):
    request_id: str
    reference_no: str
    type: str
    value: float
    issuer: str
    issuer_type: Optional[str] = None
    beneficiary: Optional[str] = None
    vendor_id: str
    vendor_name: str
    issue_date: datetime
    expiry_date: datetime
    pic_id: str
    pic_name: str
    status: str = "Active"
    next_action: Optional[str] = None

class GuaranteeUpdateDto(BaseModel):
    reference_no: Optional[str] = None
    type: Optional[str] = None
    value: Optional[float] = None
    issuer: Optional[str] = None
    issuer_type: Optional[str] = None
    beneficiary: Optional[str] = None
    issue_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    status: Optional[str] = None
    next_action: Optional[str] = None
    file_url: Optional[str] = None

class GuaranteeResponseDto(GuaranteeCreateDto):
    id: str
    file_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
