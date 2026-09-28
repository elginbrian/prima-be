"""
Pydantic schemas for Procurement requests/responses
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class BaseUserSchema(BaseModel):
    id: str
    name: str
    role: str
    department: str
    avatar: Optional[str] = None


class ProcurementRequestCreate(BaseModel):
    title: str
    pic_id: str
    fpp_id: str
    amount: float
    department: str
    stage: str = "Persiapan"
    current_step: str = "Rapat Pra-Tender"
    is_urgent: bool = False


class ProcurementRequestUpdate(BaseModel):
    stage: Optional[str] = None
    operational_status: Optional[str] = None
    operational_status_reason: Optional[str] = None
    current_step: Optional[str] = None
    is_urgent: Optional[bool] = None


class ProcurementRequestResponse(BaseModel):
    id: str
    title: str
    pic: BaseUserSchema
    fpp: BaseUserSchema
    amount: float
    stage: str
    operational_status: str
    current_step: str
    department: str
    stage_started_at: datetime
    is_urgent: bool
    created_at: datetime
    updated_at: datetime
    operational_status_reason: Optional[str] = None

    class Config:
        from_attributes = True
