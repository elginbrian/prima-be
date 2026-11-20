import io
import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Any, List, Optional

from src.infrastructure.database import get_db
from src.infrastructure.models.document_model import DocumentModel
from src.infrastructure.models.user_model import UserModel
from src.presentation.auth_dependencies import get_current_user
from src.application.dtos.document_dto import (
    DocumentResponseDto,
    DocumentCreateDto,
    DocumentUpdateDto,
    DocumentRevisionCreateDto,
)
from src.application.dtos.validation_dto import (
    ChecklistRuleItemDto,
    CreateValidationProfileDto,
    UpdateValidationProfileDto,
    ValidationProfileResponseDto,
    DocumentValidationResponseDto,
    PublishValidationToTrackerRequestDto,
    UpdateValidationDecisionDto,
    ReevaluateValidationDto,
    ValidationLogListItemDto,
)
from src.application.use_cases.validation_use_cases import (
    AnalyzeDocumentChecklistUseCase,
    ReevaluateValidationUseCase,
    PublishValidationToTrackerUseCase,
    GetValidationLogsUseCase,
    ManageValidationProfilesUseCase,
)
from src.presentation.dependencies import (
    get_analyze_document_uc,
    get_reevaluate_validation_uc,
    get_publish_validation_uc,
    get_validation_logs_uc,
    get_validation_profiles_uc,
)
from src.application.dtos.response_wrapper import success_response
from src.infrastructure.storage.s3_service import s3_service
from src.infrastructure.ai.gemini_service import gemini_service

router = APIRouter(prefix="/documents", tags=["Documents - D1 & D2"])


@router.post("/upload-local", summary="Upload a file directly to storage (S3 or local fallback)")
async def upload_file_local(
    file: UploadFile = File(...),
    key: Optional[str] = Form(None),
):
    """Direct multipart upload endpoint used as fallback when direct S3 presigned POST is unavailable."""
    target_key = key or file.filename or "upload.bin"
    file_bytes = await file.read()
    saved_key = s3_service.upload_file(io.BytesIO(file_bytes), target_key, content_type=file.content_type)
    view_url = s3_service.generate_presigned_url(saved_key, expiration=1800)
    return success_response(
        data={"key": saved_key, "url": view_url},
        message="File berhasil disimpan ke storage",
    )


# ─── MODUL D1: VALIDATION PROFILES (PUSTAKA STANDAR KELAYAKAN DOKUMEN) ────────

@router.get("/profiles", response_model=dict, summary="List validation profiles / evaluation standards")
async def list_validation_profiles(
    document_kind: Optional[str] = None,
    scope: Optional[str] = None,
    active_only: bool = True,
    uc: ManageValidationProfilesUseCase = Depends(get_validation_profiles_uc),
):
    """Fetch list of reusable validation profiles (standards) saved in DB."""
    profiles = await uc.list_profiles(document_kind=document_kind, scope=scope, active_only=active_only)
    return success_response(
        data=[p.model_dump() for p in profiles],
        message=f"Ditemukan {len(profiles)} profil standar kelayakan dokumen",
    )


@router.get("/profiles/{id}", response_model=dict, summary="Get validation profile details")
async def get_validation_profile(
    id: str,
    uc: ManageValidationProfilesUseCase = Depends(get_validation_profiles_uc),
):
    """Fetch detail of a validation profile by ID."""
    profile = await uc.get_by_id(id)
    return success_response(data=profile.model_dump(), message="Detail profil standar kelayakan berhasil diambil")


@router.post("/profiles", response_model=dict, status_code=201, summary="Create a new reusable validation profile")
async def create_validation_profile(
    payload: CreateValidationProfileDto,
    user: UserModel = Depends(get_current_user),
    uc: ManageValidationProfilesUseCase = Depends(get_validation_profiles_uc),
):
    """Create a new named validation profile/template saved in database."""
    created = await uc.create_profile(payload, actor_id=user.id, actor_name=user.name)
    return success_response(
        data=created.model_dump(),
        message=f"Profil standar '{created.name}' berhasil disimpan ke pustaka",
        code=201,
    )


@router.put("/profiles/{id}", response_model=dict, summary="Update a validation profile")
async def update_validation_profile(
    id: str,
    payload: UpdateValidationProfileDto,
    user: UserModel = Depends(get_current_user),
    uc: ManageValidationProfilesUseCase = Depends(get_validation_profiles_uc),
):
    """Update existing validation profile rules and thresholds."""
    updated = await uc.update_profile(id, payload, actor_id=user.id, actor_name=user.name)
    return success_response(
        data=updated.model_dump(),
        message=f"Profil standar '{updated.name}' berhasil diperbarui",
    )


@router.delete("/profiles/{id}", response_model=dict, summary="Delete/Deactivate a validation profile")
async def delete_validation_profile(
    id: str,
    user: UserModel = Depends(get_current_user),
    uc: ManageValidationProfilesUseCase = Depends(get_validation_profiles_uc),
):
    """Deactivate or remove a validation profile."""
    await uc.delete_profile(id)
    return success_response(message="Profil standar kelayakan berhasil dinonaktifkan")


# ─── MODUL D1: AI DOCUMENT INTAKE, CHECKLIST VALIDATION & PUBLISH ───────────

@router.post("/extract-criteria", response_model=dict, summary="Extract checklist criteria & weights from uploaded file (PDF/DOCX/XLSX/CSV)")
async def extract_criteria_from_file(
    file: UploadFile = File(...),
    ai_tier: str = Form("cekatan", description="AI model tier: cekatan | cermat | cerdas"),
    user: UserModel = Depends(get_current_user),
):
    """
    Uploads a criteria template document (PDF, DOCX, XLSX, CSV, TXT, or scanned image)
    and extracts structured checklist rules with percentage weights using Gemini AI.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File kriteria yang diunggah kosong")

    filename = file.filename or "kriteria_evaluasi.pdf"
    mime_type = file.content_type or "application/octet-stream"

    extracted = await gemini_service.extract_criteria_from_document(
        file_content=file_bytes,
        mime_type=mime_type,
        filename=filename,
        ai_tier=ai_tier,
    )
    return success_response(
        data=extracted,
        message=f"Berhasil mengekstrak {len(extracted.get('checklist_rules', []))} kriteria dari berkas '{filename}'",
        code=200,
    )


@router.post("/analyze-checklist", response_model=dict, summary="Analyze any document against checklist & prompt (Modul D1)")
async def analyze_document_checklist(
    file: UploadFile = File(...),
    request_id: Optional[str] = Form(None, description="Optional associated procurement request ID"),
    profile_id: Optional[str] = Form(None, description="Optional saved validation profile / template ID"),
    checklist_items: Optional[str] = Form(None, description="Optional ad-hoc checklist items (JSON string or newline-delimited)"),
    passing_score_threshold: Optional[float] = Form(None, description="Optional threshold score override"),
    custom_prompt: Optional[str] = Form(None, description="Optional custom prompt / instructions for AI"),
    ai_tier: str = Form("cekatan", description="AI model tier: cekatan | cermat | cerdas"),
    async_mode: bool = Form(True, description="Process AI analysis asynchronously in background"),
    user: UserModel = Depends(get_current_user),
    uc: AnalyzeDocumentChecklistUseCase = Depends(get_analyze_document_uc),
):
    """
    Modul D1: User inputs any document + optional saved validation profile or custom checklist / prompt.
    Gemini AI validates each checklist item, calculates score, enforces mandatory rules,
    provides actionable advice, and extracts workflow stages with auto-clear detection.
    """
    # 1. Parse checklist items if supplied
    parsed_items: List[Any] = []
    if checklist_items:
        try:
            loaded = json.loads(checklist_items)
            if isinstance(loaded, list):
                parsed_items = loaded
            elif isinstance(loaded, str):
                parsed_items = [s.strip() for s in loaded.split("\n") if s.strip()]
        except Exception:
            parsed_items = [s.strip() for s in checklist_items.split("\n") if s.strip()]

    # 2. Read file bytes
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File yang diunggah kosong")

    filename = file.filename or "dokumen_pengadaan.pdf"
    mime_type = file.content_type or "application/pdf"

    # 3. Execute validation use case with profile, AI tier & async background processing
    result_dto: DocumentValidationResponseDto = await uc.execute(
        file_content=file_bytes,
        filename=filename,
        mime_type=mime_type,
        profile_id=profile_id,
        checklist_items=parsed_items,
        passing_score_threshold=passing_score_threshold,
        custom_prompt=custom_prompt,
        actor_id=user.id,
        actor_name=user.name,
        request_id=request_id,
        ai_tier=ai_tier,
        async_mode=async_mode,
    )

    is_bg = result_dto.processing_status == "processing"
    return success_response(
        data=result_dto.model_dump(),
        message=(
            "Analisis AI dimulai di latar belakang. Anda dapat berpindah halaman dan akan menerima notifikasi saat selesai."
            if is_bg
            else "Dokumen berhasil dianalisis dan divalidasi terhadap standar kelayakan"
        ),
        code=202 if is_bg else 200,
    )


@router.post("/publish-to-tracker", response_model=dict, summary="Publish validated document & stages to Tracker (Modul D1 -> D3)")
async def publish_to_tracker(
    payload: PublishValidationToTrackerRequestDto,
    user: UserModel = Depends(get_current_user),
    uc: PublishValidationToTrackerUseCase = Depends(get_publish_validation_uc),
):
    """
    Converts a validated document and its extracted stages into a live Procurement Request in the Tracker,
    auto-clearing compliant stages, binding the document, and setting up initial SLAs.
    """
    result = await uc.execute(
        payload=payload,
        actor_id=user.id,
        actor_name=user.name,
    )
    return success_response(
        data=result,
        message=result.get("message", "Pekerjaan berhasil diterbitkan ke Tracker"),
        code=201,
    )


@router.get("/validations/jobs/active", response_model=dict, summary="List currently processing background AI validation jobs")
async def get_active_validation_jobs(
    db: AsyncSession = Depends(get_db),
):
    """Returns all validation logs currently running AI analysis in the background."""
    from src.infrastructure.models.validation_model import DocumentValidationLogModel
    from sqlalchemy import desc

    q = (
        select(DocumentValidationLogModel)
        .where(DocumentValidationLogModel.processing_status == "processing")
        .order_by(desc(DocumentValidationLogModel.created_at))
        .limit(20)
    )
    res = await db.execute(q)
    logs = res.scalars().all()
    data = [
        {
            "id": l.id,
            "document_name": l.document_name,
            "profile_name": l.profile_name,
            "processing_status": l.processing_status or "processing",
            "ai_tier_requested": l.ai_tier_requested,
            "ai_tier_used": l.ai_tier_used,
            "ai_model_used": l.ai_model_used,
            "ai_fallback_notice": l.ai_fallback_notice,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]
    return success_response(data=data, message=f"Ditemukan {len(data)} analisis AI aktif")


@router.get("/validations/{id}", response_model=dict, summary="Get validation log details (Audit Trail)")
async def get_validation_log_detail(
    id: str,
    uc: GetValidationLogsUseCase = Depends(get_validation_logs_uc),
):
    """Fetch immutable validation log details by ID (or linked document ID)."""
    result = await uc.get_by_id(id)
    return success_response(data=result.model_dump(), message="Detail log validasi berhasil diambil")


@router.patch("/validations/{id}/decision", response_model=dict, summary="Update reviewer decision on validation log & linked document")
async def update_validation_decision(
    id: str,
    payload: UpdateValidationDecisionDto,
    user: UserModel = Depends(get_current_user),
    uc: GetValidationLogsUseCase = Depends(get_validation_logs_uc),
):
    """Update verification status, reviewer notes, and follow-up action for a validation log & linked document."""
    result = await uc.update_decision(id, payload, actor_id=user.id, actor_name=user.name)
    return success_response(data=result.model_dump(), message="Keputusan verifikasi berhasil diperbarui")


@router.post("/validations/{id}/re-evaluate", response_model=dict, summary="Re-run Gemini AI evaluation with updated weights/criteria/prompt")
async def reevaluate_validation(
    id: str,
    payload: ReevaluateValidationDto,
    user: UserModel = Depends(get_current_user),
    uc: ReevaluateValidationUseCase = Depends(get_reevaluate_validation_uc),
):
    """Re-evaluates the stored document using real Gemini AI with adjusted criteria, weights, or guidance."""
    result = await uc.execute(id, payload, actor_id=user.id, actor_name=user.name)
    is_bg = result.processing_status == "processing"
    return success_response(
        data=result.model_dump(),
        message=(
            "Evaluasi ulang AI dimulai di latar belakang. Anda akan menerima notifikasi setelah selesai."
            if is_bg
            else "Evaluasi ulang AI berhasil diselesaikan dan diperbarui di database"
        ),
        code=202 if is_bg else 200,
    )



@router.get("/validations", response_model=dict, summary="Get validation logs for a request or recent (Audit Trail)")
async def get_validation_logs(
    request_id: Optional[str] = None,
    uc: GetValidationLogsUseCase = Depends(get_validation_logs_uc),
    db: AsyncSession = Depends(get_db),
):
    """Fetch list of validation logs, optionally filtered by request_id."""
    if request_id:
        items = await uc.get_by_request_id(request_id)
        return success_response(
            data=[i.model_dump() for i in items],
            message=f"Ditemukan {len(items)} riwayat validasi untuk pekerjaan {request_id}",
        )

    # General recent validations
    from src.infrastructure.models.validation_model import DocumentValidationLogModel
    from sqlalchemy import desc
    q = select(DocumentValidationLogModel).order_by(desc(DocumentValidationLogModel.created_at)).limit(50)
    res = await db.execute(q)
    logs = res.scalars().all()
    data = []
    for l in logs:
        ch = l.checklist_snapshot or []
        evals = l.validation_result.get("checklist_evaluations", []) if l.validation_result else []
        passed = sum(1 for e in evals if e.get("status") == "Memenuhi")
        data.append({
            "id": l.id,
            "request_id": l.request_id,
            "document_id": l.document_id,
            "profile_id": l.profile_id,
            "profile_name": l.profile_name,
            "document_name": l.document_name,
            "document_file_url": l.document_file_url,
            "overall_score": l.overall_score,
            "passing_score_threshold": l.passing_score_threshold or 80.0,
            "compliance_status": l.compliance_status,
            "checklist_count": len(ch),
            "passed_count": passed,
            "validated_by_name": l.validated_by_name,
            "created_at": l.created_at.isoformat() if l.created_at else None,
            "processing_status": l.processing_status or "completed",
            "ai_tier_requested": l.ai_tier_requested,
            "ai_tier_used": l.ai_tier_used,
            "ai_model_used": l.ai_model_used,
            "ai_fallback_notice": l.ai_fallback_notice,
            "error_message": l.error_message,
        })
    return success_response(data=data, message=f"Ditemukan {len(data)} log validasi terbaru")


# ─── MODUL D2: EXISTING DOCUMENT REPOSITORY & REVISIONS ──────────────────────

@router.get("", response_model=dict)
async def get_documents(request_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Get all documents (Modul D2 - Checklist Pratender)"""
    query = select(DocumentModel)
    if request_id:
        query = query.where(DocumentModel.request_id == request_id)
    
    result = await db.execute(query)
    docs = result.scalars().all()
    
    dto_list = []
    for d in docs:
        item = DocumentResponseDto.model_validate(d).model_dump()
        if d.file_url:
            item["file_url_signed"] = s3_service.generate_presigned_url(
                d.file_url, expiration=1800, inline_filename=d.name
            )
        dto_list.append(item)
    return success_response(data=dto_list, message="Documents fetched")


@router.get("/{id}", response_model=dict)
async def get_document_by_id(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    item = DocumentResponseDto.model_validate(doc).model_dump()
    if doc.file_url:
        item["file_url_signed"] = s3_service.generate_presigned_url(
            doc.file_url, expiration=1800, inline_filename=doc.name
        )
    return success_response(data=item, message=f"Document {id} fetched")


@router.post("", response_model=dict)
async def add_document(payload: DocumentCreateDto, db: AsyncSession = Depends(get_db)):
    """Upload / add a new document record"""
    doc = DocumentModel(**payload.model_dump())
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return success_response(data=DocumentResponseDto.model_validate(doc).model_dump(), message="Document added", code=201)


@router.put("/{id}", response_model=dict)
@router.patch("/{id}", response_model=dict)
@router.patch("/{id}/status", response_model=dict)
async def update_document(id: str, payload: DocumentUpdateDto, db: AsyncSession = Depends(get_db)):
    """Update document verification status"""
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(doc, k, v)
        
    await db.commit()
    await db.refresh(doc)
    return success_response(data=DocumentResponseDto.model_validate(doc).model_dump(), message=f"Document {id} status updated")


@router.get("/{id}/view-url", response_model=dict)
async def get_document_view_url(id: str, db: AsyncSession = Depends(get_db)):
    """Generate a presigned GET URL for viewing / downloading a document or validation log file."""
    from src.infrastructure.models.validation_model import DocumentValidationLogModel
    from sqlalchemy import desc, or_

    file_key: Optional[str] = None
    file_name: str = f"{id}.pdf"

    result = await db.execute(select(DocumentModel).where(DocumentModel.id == id))
    doc = result.scalars().first()
    if doc:
        file_key = doc.file_url
        file_name = doc.name
    else:
        val_res = await db.execute(
            select(DocumentValidationLogModel)
            .where(
                or_(
                    DocumentValidationLogModel.id == id,
                    DocumentValidationLogModel.document_id == id,
                )
            )
            .order_by(desc(DocumentValidationLogModel.created_at))
        )
        val_log = val_res.scalars().first()
        if not val_log:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
        file_key = val_log.document_file_url
        file_name = val_log.document_name

    if not file_key or not s3_service.file_exists(file_key):
        raise HTTPException(
            status_code=404,
            detail="Berkas fisik dokumen belum diunggah ke penyimpanan S3."
        )

    url = s3_service.generate_presigned_url(
        file_key,
        expiration=1800,
        inline_filename=file_name,
    )
    if not url:
        raise HTTPException(status_code=404, detail="Tautan pratinjau dokumen tidak tersedia.")
    return success_response(
        data={"view_url": url, "file_name": file_name},
        message="View URL generated"
    )


@router.delete("/{id}", response_model=dict)
async def delete_document(id: str, db: AsyncSession = Depends(get_db)):
    """Delete a document record and remove its stored S3/local file."""
    from src.infrastructure.models.validation_model import DocumentValidationLogModel

    result = await db.execute(select(DocumentModel).where(DocumentModel.id == id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.file_url:
        s3_service.delete_file(doc.file_url)

    val_res = await db.execute(
        select(DocumentValidationLogModel).where(DocumentValidationLogModel.document_id == id)
    )
    for val_log in val_res.scalars().all():
        val_log.document_id = None

    await db.delete(doc)
    await db.commit()
    return success_response(data=None, message=f"Document {id} deleted")


@router.post("/{id}/revision", response_model=dict)
async def create_document_revision(id: str, payload: DocumentRevisionCreateDto, db: AsyncSession = Depends(get_db)):
    """Submit a new revision (v2, v3, ...) of an existing document"""
    from sqlalchemy import or_
    from src.infrastructure.models.activity_model import ProcurementActivityLogModel

    result = await db.execute(select(DocumentModel).where(DocumentModel.id == id))
    parent_doc = result.scalars().first()
    if not parent_doc:
        raise HTTPException(status_code=404, detail="Document not found")

    root_id = parent_doc.parent_document_id if parent_doc.parent_document_id else parent_doc.id

    # Determine highest version number
    family_res = await db.execute(
        select(DocumentModel).where(
            or_(DocumentModel.id == root_id, DocumentModel.parent_document_id == root_id)
        )
    )
    all_family = family_res.scalars().all()
    max_v = max([d.version_number for d in all_family], default=1)
    new_v = max_v + 1

    new_doc = DocumentModel(
        request_id=parent_doc.request_id,
        name=payload.name or parent_doc.name,
        type=parent_doc.type,
        document_kind=parent_doc.document_kind,
        status="Belum Dicek",
        pic_id=payload.pic_id,
        pic_name=payload.pic_name,
        issues=[],
        next_action="Menunggu verifikasi ulang oleh tim pengadaan",
        procurement_step=parent_doc.procurement_step,
        document_date=payload.document_date or parent_doc.document_date,
        document_number=payload.document_number or parent_doc.document_number,
        file_url=payload.file_url or parent_doc.file_url,
        mime_type=payload.mime_type or parent_doc.mime_type,
        version_number=new_v,
        parent_document_id=root_id,
        revision_notes=payload.revision_notes,
    )
    db.add(new_doc)

    # Activity log
    act_log = ProcurementActivityLogModel(
        request_id=parent_doc.request_id,
        user_id=payload.pic_id,
        user_name=payload.pic_name,
        action="DOCUMENT_REVISED",
        previous_state=f"v{parent_doc.version_number} ({parent_doc.status})",
        new_state=f"v{new_v} (Belum Dicek)",
        notes=f"Revisi dokumen '{new_doc.name}' diunggah: {payload.revision_notes}"
    )
    db.add(act_log)

    await db.commit()
    await db.refresh(new_doc)

    return success_response(
        data=DocumentResponseDto.model_validate(new_doc).model_dump(),
        message=f"Document revision v{new_v} created",
        code=201
    )


@router.get("/{id}/revisions", response_model=dict)
async def get_document_revisions(id: str, db: AsyncSession = Depends(get_db)):
    """Get all versions / revision history of a document"""
    from sqlalchemy import or_

    result = await db.execute(select(DocumentModel).where(DocumentModel.id == id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    root_id = doc.parent_document_id if doc.parent_document_id else doc.id

    rev_res = await db.execute(
        select(DocumentModel)
        .where(or_(DocumentModel.id == root_id, DocumentModel.parent_document_id == root_id))
        .order_by(DocumentModel.version_number.asc())
    )
    revisions = rev_res.scalars().all()
    data = [DocumentResponseDto.model_validate(r).model_dump() for r in revisions]

    return success_response(data=data, message=f"Fetched {len(data)} document versions")
