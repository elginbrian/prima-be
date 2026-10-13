from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from src.infrastructure.database import get_db
from src.infrastructure.models.document_model import DocumentModel
from src.application.dtos.document_dto import DocumentResponseDto, DocumentCreateDto, DocumentUpdateDto, DocumentRevisionCreateDto
from src.application.dtos.response_wrapper import success_response
from src.infrastructure.storage.s3_service import s3_service

router = APIRouter(prefix="/documents", tags=["Documents - D2"])

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
    """Upload / add a new document"""
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
