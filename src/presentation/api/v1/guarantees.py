from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import uuid4

from src.infrastructure.database import get_db
from src.infrastructure.models.guarantee_model import GuaranteeModel
from src.application.dtos.response_wrapper import success_response, error_response
from src.application.dtos.guarantee_dto import (
    GuaranteeCreateDto,
    GuaranteeUpdateDto,
    GuaranteeResponseDto,
    ClaimGuaranteeDto,
    ReleaseGuaranteeDto,
    AmendGuaranteeDto,
)
from src.infrastructure.storage.s3_service import s3_service
from src.infrastructure.ai.gemini_service import gemini_service
from src.infrastructure.config import settings
from src.domain.exceptions import ValidationException

from src.infrastructure.models.procurement_model import ProcurementRequestModel

router = APIRouter(prefix="/guarantees", tags=["Guarantees - D2"])

ALLOWED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}

def _evaluate_threshold(guarantee_type: str, value: float, procurement_amount: Optional[float]):
    if not procurement_amount or procurement_amount <= 0:
        return True, 0.0, None
    
    g_type = (guarantee_type or "").lower()
    val = value or 0.0
    
    if "pelaksanaan" in g_type or "pemeliharaan" in g_type:
        min_required = round(procurement_amount * 0.05, 2)
        if val < min_required:
            return False, min_required, f"Nilai jaminan (Rp {val:,.0f}) di bawah ambang batas minimal 5% nilai kontrak (Rp {min_required:,.0f})"
        return True, min_required, None
        
    if "penawaran" in g_type:
        min_required = round(procurement_amount * 0.01, 2)
        if val < min_required:
            return False, min_required, f"Nilai jaminan (Rp {val:,.0f}) di bawah ambang batas minimal 1% pagu tender (Rp {min_required:,.0f})"
        return True, min_required, None
        
    return True, 0.0, None

@router.post("/extract")
async def extract_guarantee(file: UploadFile = File(...)):
    """Extract data from guarantee document using AI"""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationException("Format file tidak didukung. Gunakan PDF, JPG, atau PNG.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValidationException(f"Ukuran file melebihi batas {settings.max_upload_mb} MB.")
    if not content:
        raise ValidationException("File kosong.")

    data = await gemini_service.extract_guarantee_data(content, file.content_type)
    return success_response(data=data, message="Data extracted successfully")


@router.get("")
async def get_guarantees(request_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Get all guarantees (Modul D2 - Monitoring Jaminan). Optionally filter by request_id."""
    query = select(GuaranteeModel)
    if request_id:
        query = query.where(GuaranteeModel.request_id == request_id)
        
    result = await db.execute(query)
    guarantees = result.scalars().all()
    
    req_ids = list({g.request_id for g in guarantees if g.request_id})
    req_amounts = {}
    if req_ids:
        req_res = await db.execute(
            select(ProcurementRequestModel.id, ProcurementRequestModel.amount).where(
                ProcurementRequestModel.id.in_(req_ids)
            )
        )
        for r_id, r_amt in req_res.all():
            req_amounts[r_id] = r_amt

    # Process presigned urls and threshold check
    data = []
    for g in guarantees:
        g_data = GuaranteeResponseDto.model_validate(g).model_dump(mode="json")
        if g.file_url and not g.file_url.startswith("http"):
            url = s3_service.generate_presigned_url(g.file_url)
            g_data["file_url_signed"] = url if url else g.file_url
        
        amt = req_amounts.get(g.request_id)
        compliant, min_req, warning = _evaluate_threshold(g.type, g.value, amt)
        g_data["is_threshold_compliant"] = compliant
        g_data["min_required_value"] = min_req
        g_data["threshold_warning"] = warning
        data.append(g_data)
        
    return success_response(data=data, message="Guarantees fetched")


@router.get("/{id}")
async def get_guarantee_by_id(id: str, db: AsyncSession = Depends(get_db)):
    query = select(GuaranteeModel).where(GuaranteeModel.id == id)
    result = await db.execute(query)
    guarantee = result.scalar_one_or_none()
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")
        
    g_data = GuaranteeResponseDto.model_validate(guarantee).model_dump(mode="json")
    if guarantee.file_url and not guarantee.file_url.startswith("http"):
        url = s3_service.generate_presigned_url(guarantee.file_url)
        g_data["file_url_signed"] = url if url else guarantee.file_url
    
    p_req = await db.scalar(
        select(ProcurementRequestModel).where(ProcurementRequestModel.id == guarantee.request_id)
    )
    amt = p_req.amount if p_req else None
    compliant, min_req, warning = _evaluate_threshold(guarantee.type, guarantee.value, amt)
    g_data["is_threshold_compliant"] = compliant
    g_data["min_required_value"] = min_req
    g_data["threshold_warning"] = warning
        
    return success_response(data=g_data, message=f"Guarantee {id} fetched")


@router.post("")
async def add_guarantee(payload: GuaranteeCreateDto, db: AsyncSession = Depends(get_db)):
    """Add a new guarantee"""
    new_id = f"G-{uuid4().hex[:8].upper()}"
    guarantee = GuaranteeModel(id=new_id, **payload.model_dump())
    db.add(guarantee)
    await db.commit()
    await db.refresh(guarantee)

    g_data = GuaranteeResponseDto.model_validate(guarantee).model_dump(mode="json")
    p_req = await db.scalar(
        select(ProcurementRequestModel).where(ProcurementRequestModel.id == guarantee.request_id)
    )
    amt = p_req.amount if p_req else None
    compliant, min_req, warning = _evaluate_threshold(guarantee.type, guarantee.value, amt)
    g_data["is_threshold_compliant"] = compliant
    g_data["min_required_value"] = min_req
    g_data["threshold_warning"] = warning
    
    return success_response(
        data=g_data,
        message="Guarantee added",
        code=201
    )


@router.patch("/{id}")
async def update_guarantee(id: str, payload: GuaranteeUpdateDto, db: AsyncSession = Depends(get_db)):
    """Update guarantee details (e.g. extend expiry)"""
    query = select(GuaranteeModel).where(GuaranteeModel.id == id)
    result = await db.execute(query)
    guarantee = result.scalar_one_or_none()
    
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")
        
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(guarantee, key, value)
        
    await db.commit()
    await db.refresh(guarantee)

    g_data = GuaranteeResponseDto.model_validate(guarantee).model_dump(mode="json")
    p_req = await db.scalar(
        select(ProcurementRequestModel).where(ProcurementRequestModel.id == guarantee.request_id)
    )
    amt = p_req.amount if p_req else None
    compliant, min_req, warning = _evaluate_threshold(guarantee.type, guarantee.value, amt)
    g_data["is_threshold_compliant"] = compliant
    g_data["min_required_value"] = min_req
    g_data["threshold_warning"] = warning
    
    return success_response(
        data=g_data,
        message=f"Guarantee {id} updated"
    )

@router.delete("/{id}")
async def delete_guarantee(id: str, db: AsyncSession = Depends(get_db)):
    """Delete a guarantee (used to roll back a failed upload)."""
    result = await db.execute(select(GuaranteeModel).where(GuaranteeModel.id == id))
    guarantee = result.scalar_one_or_none()
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")

    await db.delete(guarantee)
    await db.commit()
    return success_response(data=None, message=f"Guarantee {id} deleted")


@router.get("/{id}/upload-url")
async def get_upload_url(id: str, content_type: str, db: AsyncSession = Depends(get_db)):
    """Generate a presigned URL to upload a guarantee document directly to S3"""
    extension = ALLOWED_CONTENT_TYPES.get(content_type)
    if not extension:
        raise ValidationException("Format file tidak didukung. Gunakan PDF, JPG, atau PNG.")

    query = select(GuaranteeModel).where(GuaranteeModel.id == id)
    result = await db.execute(query)
    guarantee = result.scalar_one_or_none()
    
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")
        
    object_name = f"guarantees/{id}/{uuid4().hex}.{extension}"
    
    # Generate presigned POST url (size-limited, see S3Service)
    upload_info = s3_service.generate_presigned_post(
        object_name, content_type, max_bytes=settings.max_upload_mb * 1024 * 1024
    )
    
    if not upload_info:
        raise HTTPException(status_code=503, detail="Penyimpanan file belum tersedia. Hubungi administrator.")
        
    return success_response(
        data={
            "presigned_post": upload_info,
            "object_key": object_name
        },
        message="Upload URL generated"
    )


@router.post("/{id}/claim")
async def claim_guarantee(id: str, payload: ClaimGuaranteeDto, db: AsyncSession = Depends(get_db)):
    """Initiate a formal claim for a guarantee due to vendor default"""
    result = await db.execute(select(GuaranteeModel).where(GuaranteeModel.id == id))
    guarantee = result.scalar_one_or_none()
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")
    
    guarantee.status = "Klaim Diajukan"
    guarantee.next_action = f"Klaim diajukan ke {guarantee.issuer} (Surat: {payload.claim_letter_no}). Alasan: {payload.claim_reason}"
    await db.commit()
    await db.refresh(guarantee)
    return success_response(
        data=GuaranteeResponseDto.model_validate(guarantee).model_dump(mode="json"),
        message="Klaim jaminan berhasil diajukan"
    )


@router.post("/{id}/release")
async def release_guarantee(id: str, payload: ReleaseGuaranteeDto, db: AsyncSession = Depends(get_db)):
    """Release/return original physical guarantee to vendor after project completion (BAST)"""
    result = await db.execute(select(GuaranteeModel).where(GuaranteeModel.id == id))
    guarantee = result.scalar_one_or_none()
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")
    
    guarantee.status = "Dikembalikan"
    guarantee.next_action = f"Warkat jaminan telah dikembalikan ke vendor (BAST: {payload.bast_no})"
    await db.commit()
    await db.refresh(guarantee)
    return success_response(
        data=GuaranteeResponseDto.model_validate(guarantee).model_dump(mode="json"),
        message="Jaminan berhasil dikembalikan ke vendor"
    )


@router.post("/{id}/amend")
async def amend_guarantee(id: str, payload: AmendGuaranteeDto, db: AsyncSession = Depends(get_db)):
    """Extend expiry date or amend guarantee value following project addendum"""
    result = await db.execute(select(GuaranteeModel).where(GuaranteeModel.id == id))
    guarantee = result.scalar_one_or_none()
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")
    
    guarantee.expiry_date = payload.new_expiry_date
    if payload.new_value is not None:
        guarantee.value = payload.new_value
    guarantee.status = "Active"
    expiry_formatted = payload.new_expiry_date.strftime("%d-%m-%Y")
    guarantee.next_action = f"Amandemen disetujui (No: {payload.amendment_no}) s.d. {expiry_formatted}"
    await db.commit()
    await db.refresh(guarantee)
    return success_response(
        data=GuaranteeResponseDto.model_validate(guarantee).model_dump(mode="json"),
        message=f"Jaminan berhasil diperpanjang hingga {expiry_formatted}"
    )


@router.get("/{id}/view-url")
async def get_guarantee_view_url(id: str, db: AsyncSession = Depends(get_db)):
    """Generate a presigned GET URL for viewing / downloading the guarantee document"""
    result = await db.execute(select(GuaranteeModel).where(GuaranteeModel.id == id))
    guarantee = result.scalar_one_or_none()
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")

    file_key = guarantee.file_url or f"guarantees/{id}.pdf"
    url = s3_service.generate_presigned_url(file_key, expiration=1800)
    if not url:
        url = guarantee.file_url or f"https://s3.ap-southeast-1.amazonaws.com/prima-storage/{file_key}"
    return success_response(
        data={"view_url": url, "file_name": f"Jaminan_{guarantee.reference_no.replace('/', '_')}.pdf"},
        message="View URL generated"
    )
