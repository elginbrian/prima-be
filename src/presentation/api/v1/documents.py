from fastapi import APIRouter
from src.application.dtos.response_wrapper import success_response

router = APIRouter(prefix="/documents", tags=["Documents - D1"])


@router.get("")
async def get_documents():
    """Get all documents (Modul D1 - Checklist Pratender)"""
    return success_response(data=[], message="Documents fetched")


@router.get("/{id}")
async def get_document_by_id(id: str):
    return success_response(data=None, message=f"Document {id} fetched")


@router.post("")
async def add_document():
    """Upload / add a new document"""
    return success_response(data=None, message="Document added", code=201)


@router.patch("/{id}/status")
async def update_document_status(id: str):
    """Update document verification status (Lulus Verifikasi / Catatan Procurement / Tindak Lanjut FPP)"""
    return success_response(data=None, message=f"Document {id} status updated")
