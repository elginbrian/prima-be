"""
Validation & Workflow DTOs (Modul D1 & Audit Trail D2/D3/D4)

Pydantic schemas for document checklist analysis (with percentage weights & normalization),
criteria file extraction, AI re-evaluation, project publishing, and Admin workflow stages.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class ChecklistItemResultDto(BaseModel):
    item: str = Field(..., description="Checklist item tested")
    status: str = Field(..., description="Evaluation status: Memenuhi | Tidak Memenuhi | Perlu Perhatian")
    evidence_quote: Optional[str] = Field(None, description="Exact text quotation from document serving as proof")
    explanation: Optional[str] = Field(None, description="Detailed explanation of the findings")
    comparison_detail: Optional[str] = Field(None, description="Quantitative/comparative check summary (e.g. 12 bln vs 13 bln)")
    severity: str = Field("SUCCESS", description="Severity level: SUCCESS | WARNING | ERROR")
    is_mandatory: bool = Field(False, description="Whether this item was marked as mandatory")
    weight: float = Field(0.0, description="Configured raw weight percentage for this criterion")
    normalized_weight: float = Field(0.0, description="Normalized percentage weight summing to 100%")
    fulfillment_ratio: float = Field(1.0, description="Fulfillment ratio between 0.0 and 1.0")
    earned_score: float = Field(0.0, description="Weighted score points earned (normalized_weight * fulfillment_ratio)")
    source: Optional[str] = Field(None, description="Origin of criterion: template | custom")


class ChecklistRuleItemDto(BaseModel):
    category: str = Field("Umum", description="Rule category (Legalitas, Finansial, Teknis, Waktu, HSSE)")
    item: str = Field(..., description="Checklist rule requirement text")
    guidance: Optional[str] = Field(None, description="Detailed guidance or comparison target for AI evaluation")
    is_mandatory: bool = Field(True, description="Whether failing this rule automatically disqualifies the document")
    weight: float = Field(20.0, ge=0.0, le=100.0, description="Weight percentage of this rule in total score")
    severity_on_failure: str = Field("ERROR", description="Severity if this check fails: ERROR | WARNING")
    source: Optional[str] = Field(None, description="Criterion origin: template | custom")


class ExtractedCriteriaResponseDto(BaseModel):
    suggested_name: str
    suggested_document_kind: str = "Umum"
    suggested_system_prompt: Optional[str] = None
    checklist_rules: List[ChecklistRuleItemDto] = Field(default_factory=list)
    ai_tier_requested: Optional[str] = None
    ai_tier_used: Optional[str] = None
    ai_model_used: Optional[str] = None
    ai_fallback_notice: Optional[str] = None


class CreateValidationProfileDto(BaseModel):
    name: str = Field(..., description="Profile / Template name")
    code: Optional[str] = Field(None, description="Unique code or slug")
    document_kind: str = Field("Umum", description="Document type")
    description: Optional[str] = Field(None, description="Detailed description of this validation standard")
    scope: str = Field("GLOBAL", description="Governance scope: GLOBAL | IT | INFRASTRUCTURE | SERVICES")
    department_id: Optional[str] = Field(None, description="Specific department owner ID if applicable")
    department_name: Optional[str] = Field(None, description="Specific department owner name if applicable")
    passing_score_threshold: float = Field(80.0, description="Minimum score required to achieve 'Lulus Verifikasi'")
    warning_score_threshold: float = Field(60.0, description="Score threshold for 'Catatan Procurement'")
    strict_mandatory_enforcement: bool = Field(True, description="If true, 1 failed mandatory item drops status to 'Perlu Perbaikan'")
    target_stage_to_clear: Optional[str] = Field(None, description="Workflow stage to auto-clear if this validation passes")
    custom_system_prompt: Optional[str] = Field(None, description="Special AI instructions or regulatory references")
    checklist_rules: List[ChecklistRuleItemDto] = Field(default_factory=list, description="List of weighted checklist rules")
    is_default: bool = Field(False, description="Whether this is the default profile for its document kind")


class UpdateValidationProfileDto(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    document_kind: Optional[str] = None
    description: Optional[str] = None
    scope: Optional[str] = None
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    passing_score_threshold: Optional[float] = None
    warning_score_threshold: Optional[float] = None
    strict_mandatory_enforcement: Optional[bool] = None
    target_stage_to_clear: Optional[str] = None
    custom_system_prompt: Optional[str] = None
    checklist_rules: Optional[List[ChecklistRuleItemDto]] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class ValidationProfileResponseDto(BaseModel):
    id: str
    name: str
    code: Optional[str] = None
    document_kind: str
    description: Optional[str] = None
    scope: str
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    passing_score_threshold: float
    warning_score_threshold: float
    strict_mandatory_enforcement: bool
    target_stage_to_clear: Optional[str] = None
    custom_system_prompt: Optional[str] = None
    checklist_rules: List[ChecklistRuleItemDto] = Field(default_factory=list)
    is_default: bool
    is_active: bool
    created_by_id: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ExtractedStageDto(BaseModel):
    step: str = Field(..., description="Name of the workflow milestone step")
    status: str = Field("Pending", description="Stage status: Done | In Progress | Pending")
    auto_cleared: bool = Field(False, description="Whether this stage was automatically verified and cleared by the document")
    notes: Optional[str] = Field(None, description="Context notes or reasons for the stage state")


class ExtractedProjectDto(BaseModel):
    title: str = Field(..., description="Detected or generated procurement job title")
    estimated_amount: float = Field(0.0, description="Estimated total budget / HPS amount in IDR")
    suggested_method: str = Field("Tender Terbuka", description="Procurement method")
    department_name: str = Field("Procurement & General Support", description="Originating department or unit")
    stages: List[ExtractedStageDto] = Field(default_factory=list, description="Extracted workflow stages")


class DocumentValidationResponseDto(BaseModel):
    id: str = Field(..., description="Validation log record ID")
    document_name: str = Field(..., description="Original filename of the analyzed document")
    document_file_url: Optional[str] = Field(None, description="S3 URL or path to uploaded document")
    mime_type: Optional[str] = Field(None, description="Document MIME type")
    profile_id: Optional[str] = Field(None, description="Used validation profile template ID")
    profile_name: Optional[str] = Field(None, description="Used validation profile template name")
    overall_score: float = Field(..., description="Weighted document compliance score between 0 and 100")
    passing_score_threshold: float = Field(80.0, description="Applied passing score threshold")
    compliance_status: str = Field(..., description="Lulus Verifikasi | Catatan Procurement | Perlu Perbaikan")
    summary: str = Field(..., description="AI Executive summary of the document check")
    user_prompt: Optional[str] = Field(None, description="Custom AI prompt used for this evaluation")
    checklist_rules: List[ChecklistRuleItemDto] = Field(default_factory=list, description="Snapshot of weighted checklist rules used")
    checklist_evaluations: List[ChecklistItemResultDto] = Field(default_factory=list, description="Detailed item-by-item results")
    recommendations: List[str] = Field(default_factory=list, description="Actionable recommendations to fix deficiencies")
    extracted_project: ExtractedProjectDto = Field(..., description="Extracted project and workflow stages")
    created_at: datetime = Field(..., description="Timestamp of the validation run")
    request_id: Optional[str] = Field(None, description="Linked procurement request ID (if already published)")
    document_id: Optional[str] = Field(None, description="Linked document record ID (if already published)")
    processing_status: str = Field("completed", description="processing | completed | failed")
    ai_tier_requested: Optional[str] = Field(None, description="Requested AI tier: cekatan | cermat | cerdas")
    ai_tier_used: Optional[str] = Field(None, description="Actual AI tier used: cekatan | cermat | cerdas | gemma")
    ai_model_used: Optional[str] = Field(None, description="Exact Gemini/Gemma model ID used")
    ai_fallback_notice: Optional[str] = Field(None, description="Automatic notification when AI stepped down to a smaller model")
    error_message: Optional[str] = Field(None, description="Error details when processing_status == failed")


class ReevaluateValidationDto(BaseModel):
    checklist_rules: Optional[List[ChecklistRuleItemDto]] = Field(None, description="Updated checklist rules with weights")
    passing_score_threshold: Optional[float] = Field(None, description="Updated passing threshold")
    custom_prompt: Optional[str] = Field(None, description="Updated/additional AI guidance prompt")
    ai_tier: Optional[str] = Field("cekatan", description="AI model tier: cekatan | cermat | cerdas")
    async_mode: Optional[bool] = Field(True, description="Run re-evaluation in background and return immediately")


class PublishValidationToTrackerRequestDto(BaseModel):
    validation_log_id: str = Field(..., description="Validation log ID generated from the analysis step")
    target_request_id: Optional[str] = Field(None, description="Bind document & auto-clear stages on an existing procurement request")
    title: Optional[str] = Field(None, description="Custom title override for the procurement project")
    amount: Optional[float] = Field(None, description="Custom budget amount override in IDR")
    procurement_method: Optional[str] = Field(None, description="Procurement method override")
    vendor_name: Optional[str] = Field(None, description="Vendor name override")
    department_id: Optional[str] = Field("DEPT-PROC", description="Department identifier")
    department_name: Optional[str] = Field("Procurement & General Support", description="Department display name")
    fpp_id: Optional[str] = Field("FPP-ENG", description="FPP user ID")
    fpp_name: Optional[str] = Field("Fungsi Pemohon Pengadaan", description="FPP display name")
    pic_id: Optional[str] = Field(None, description="PIC user ID")
    pic_name: Optional[str] = Field(None, description="PIC display name")
    stages: Optional[List[ExtractedStageDto]] = Field(None, description="Custom stages (overriding AI suggestions)")
    notes: Optional[str] = Field(None, description="Additional administrative remarks")


class UpdateValidationDecisionDto(BaseModel):
    compliance_status: str = Field(..., description="Lulus Verifikasi | Catatan Procurement | Tindak Lanjut FPP | Perlu Perbaikan")
    overall_score: Optional[float] = Field(None, description="Optional manual score adjustment (0-100)")
    reviewer_notes: Optional[str] = Field(None, description="Manual reviewer notes appended to summary")
    next_action: Optional[str] = Field(None, description="Follow-up action for FPP or Procurement")


class ValidationLogListItemDto(BaseModel):
    id: str
    request_id: Optional[str] = None
    document_id: Optional[str] = None
    profile_id: Optional[str] = None
    profile_name: Optional[str] = None
    document_name: str
    document_file_url: Optional[str] = None
    overall_score: float
    passing_score_threshold: Optional[float] = 80.0
    compliance_status: str
    checklist_count: int
    passed_count: int
    validated_by_name: Optional[str] = None
    created_at: datetime
    processing_status: str = "completed"
    ai_tier_requested: Optional[str] = None
    ai_tier_used: Optional[str] = None
    ai_model_used: Optional[str] = None
    ai_fallback_notice: Optional[str] = None
    error_message: Optional[str] = None


# ─── ADMIN WORKFLOW STAGES DTOs ──────────────────────────────────────────────

class WorkflowStageCreateDto(BaseModel):
    procurement_method: str = Field("Tender Terbuka", description="Procurement method name")
    step_name: str = Field(..., min_length=2, max_length=200, description="Stage / step display name")
    stage_group: str = Field("Sourcing", description="Persiapan | Sourcing | Evaluasi | Contracting | Selesai")
    order_index: Optional[int] = Field(None, description="Optional ordering index")
    default_sla_days: Optional[int] = Field(5, ge=1, le=180, description="Default SLA duration in days")
    description: Optional[str] = Field(None, description="Optional explanation of this stage")


class WorkflowStageUpdateDto(BaseModel):
    procurement_method: Optional[str] = None
    step_name: Optional[str] = None
    stage_group: Optional[str] = None
    order_index: Optional[int] = None
    default_sla_days: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class WorkflowStageReorderDto(BaseModel):
    procurement_method: str
    ordered_stage_ids: List[str]


class WorkflowStageResponseDto(BaseModel):
    id: str
    procurement_method: str
    step_name: str
    stage_group: str
    order_index: int
    default_sla_days: Optional[int] = 5
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
