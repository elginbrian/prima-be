from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class OmniAssistantQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1500, description="Pertanyaan atau perintah pengguna")


class OmniReferencedItemDto(BaseModel):
    id: str
    category: str
    title: str
    subtitle: str
    badge: Optional[str] = None
    is_urgent: bool = False
    href: Optional[str] = None


class OmniCommandDto(BaseModel):
    type: Literal[
        "NAVIGATE",
        "COMPLETE_SLA",
        "ESCALATE_SLA",
        "SUBMIT_RECOVERY_PLAN",
        "UPDATE_JOB_STATUS",
        "MOVE_JOB_STAGE",
        "CREATE_PROCUREMENT",
        "EVALUATE_SLA",
    ]
    label: str
    description: Optional[str] = None
    auto_execute: bool = False
    params: Dict[str, Any] = Field(default_factory=dict)


class OmniAssistantResponseDto(BaseModel):
    intent_kind: Literal["QUESTION", "COMMAND", "HYBRID"] = "QUESTION"
    answer: str
    highlights: List[str] = Field(default_factory=list)
    referenced_items: List[OmniReferencedItemDto] = Field(default_factory=list)
    command: Optional[OmniCommandDto] = None
    suggested_followups: List[str] = Field(default_factory=list)
    ai_tier_requested: str = "cekatan"
    ai_tier_used: str = "cekatan"
    ai_model_used: Optional[str] = None
    ai_fallback_notice: Optional[str] = None
