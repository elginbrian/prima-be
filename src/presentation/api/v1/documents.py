import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

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
    ValidationLogListItemDto,
)
from src.application.use_cases.validation_use_cases import (
    AnalyzeDocumentChecklistUseCase,
    PublishValidationToTrackerUseCase,
    GetValidationLogsUseCase,
    ManageValidationProfilesUseCase,
)
from src.presentation.dependencies import (
    get_analyze_document_uc,
    get_publish_validation_uc,
    get_validation_logs_uc,
    get_validation_profiles_uc,
)
from src.application.dtos.response_wrapper import success_response
from src.infrastructure.storage.s3_service import s3_service

router = APIRouter(prefix="/documents", tags=["Documents - D1 & D2"])


@router.post("/upload-local", summary="Upload a file directly to local storage / Docker volume")
async def upload_file_local(
    file: UploadFile = File(...),
    key: Optional[str] = Form(None),
):
    """Endpoint for direct client file uploads in local volume storage mode."""
    target_key = key or file.filename or "upload.bin"
    file_bytes = await file.read()
    saved_key = s3_service.upload_file(io.BytesIO(file_bytes), target_key, content_type=file.content_type)
    return success_response(
        data={"key": saved_key, "url": f"/uploads/{saved_key}"},
        message="File berhasil disimpan di storage lokal",
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

@router.post("/analyze-checklist", response_model=dict, summary="Analyze any document against checklist & prompt (Modul D1)")
async def analyze_document_checklist(
    file: UploadFile = File(...),
    request_id: Optional[str] = Form(None, description="Optional associated procurement request ID"),
    profile_id: Optional[str] = Form(None, description="Optional saved validation profile / template ID"),
    checklist_items: Optional[str] = Form(None, description="Optional ad-hoc checklist items (JSON string or newline-delimited)"),
    passing_score_threshold: Optional[float] = Form(None, description="Optional threshold score override"),
    custom_prompt: Optional[str] = Form(None, description="Optional custom prompt / instructions for AI"),
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

    # 3. Execute validation use case with profile & threshold support
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
    )

    return success_response(
        data=result_dto.model_dump(),
        message="Dokumen berhasil dianalisis dan divalidasi terhadap standar kelayakan",
        code=200,
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
            "document_name": l.document_name,
            "document_file_url": l.document_file_url,
            "overall_score": l.overall_score,
            "compliance_status": l.compliance_status,
            "checklist_count": len(ch),
            "passed_count": passed,
            "validated_by_name": l.validated_by_name,
            "created_at": l.created_at.isoformat() if l.created_at else None,
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
    
    dto_list = [DocumentResponseDto.model_validate(d).model_dump() for d in docs]
    return success_response(data=dto_list, message="Documents fetched")


@router.get("/{id}", response_model=dict)
async def get_document_by_id(id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return success_response(data=DocumentResponseDto.model_validate(doc).model_dump(), message=f"Document {id} fetched")


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
    """Generate a presigned GET URL for viewing / downloading the document"""
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_key = doc.file_url or f"documents/{id}.pdf"
    url = s3_service.generate_presigned_url(file_key, expiration=1800)
    if not url:
        url = doc.file_url or f"https://s3.ap-southeast-1.amazonaws.com/prima-storage/{file_key}"
    return success_response(
        data={"view_url": url, "file_name": doc.name},
        message="View URL generated"
    )


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
