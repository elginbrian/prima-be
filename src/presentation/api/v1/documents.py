from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from src.infrastructure.database import get_db
from src.infrastructure.models.document_model import DocumentModel
from src.application.dtos.document_dto import DocumentResponseDto, DocumentCreateDto, DocumentUpdateDto
from src.application.dtos.response_wrapper import success_response

router = APIRouter(prefix="/documents", tags=["Documents - D2"])

@router.get("", response_model=dict)
def get_documents(request_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Get all documents (Modul D2 - Checklist Pratender)"""
    query = db.query(DocumentModel)
    if request_id:
        query = query.filter(DocumentModel.request_id == request_id)
    
    docs = query.all()
    # Pydantic will parse it correctly in response_model but we can just use dict for success_response
    dto_list = [DocumentResponseDto.model_validate(d).model_dump() for d in docs]
    return success_response(data=dto_list, message="Documents fetched")

@router.get("/{id}", response_model=dict)
def get_document_by_id(id: str, db: Session = Depends(get_db)):
    doc = db.query(DocumentModel).filter(DocumentModel.id == id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return success_response(data=DocumentResponseDto.model_validate(doc).model_dump(), message=f"Document {id} fetched")

@router.post("", response_model=dict)
def add_document(payload: DocumentCreateDto, db: Session = Depends(get_db)):
    """Upload / add a new document"""
    doc = DocumentModel(**payload.model_dump())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return success_response(data=DocumentResponseDto.model_validate(doc).model_dump(), message="Document added", code=201)

@router.put("/{id}", response_model=dict)
def update_document(id: str, payload: DocumentUpdateDto, db: Session = Depends(get_db)):
    """Update document verification status"""
    doc = db.query(DocumentModel).filter(DocumentModel.id == id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(doc, k, v)
        
    db.commit()
    db.refresh(doc)
    return success_response(data=DocumentResponseDto.model_validate(doc).model_dump(), message=f"Document {id} status updated")
