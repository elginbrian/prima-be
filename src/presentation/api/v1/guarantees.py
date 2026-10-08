from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import uuid4

from src.infrastructure.database import get_db
from src.infrastructure.models.guarantee_model import GuaranteeModel
from src.application.dtos.response_wrapper import success_response, error_response
from src.application.dtos.guarantee_dto import GuaranteeCreateDto, GuaranteeUpdateDto, GuaranteeResponseDto
from src.infrastructure.storage.s3_service import s3_service
from src.infrastructure.ai.gemini_service import gemini_service

router = APIRouter(prefix="/guarantees", tags=["Guarantees - D2"])

@router.post("/extract")
async def extract_guarantee(file: UploadFile = File(...)):
    """Extract data from guarantee document using AI"""
    try:
        content = await file.read()
        data = await gemini_service.extract_guarantee_data(content, file.content_type)
        return success_response(data=data, message="Data extracted successfully")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def get_guarantees(request_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Get all guarantees (Modul D2 - Monitoring Jaminan). Optionally filter by request_id."""
    query = select(GuaranteeModel)
    if request_id:
        query = query.where(GuaranteeModel.request_id == request_id)
        
    result = await db.execute(query)
    guarantees = result.scalars().all()
    
    # Process presigned urls if file_url exists but is an s3 key
    data = []
    for g in guarantees:
        g_data = GuaranteeResponseDto.model_validate(g).model_dump(mode="json")
        if g.file_url and not g.file_url.startswith("http"):
            # generate presigned url for reading
            url = s3_service.generate_presigned_url(g.file_url)
            g_data["file_url_signed"] = url if url else g.file_url
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
        
    return success_response(data=g_data, message=f"Guarantee {id} fetched")


@router.post("")
async def add_guarantee(payload: GuaranteeCreateDto, db: AsyncSession = Depends(get_db)):
    """Add a new guarantee"""
    new_id = f"G-{uuid4().hex[:8].upper()}"
    guarantee = GuaranteeModel(id=new_id, **payload.model_dump())
    db.add(guarantee)
    await db.commit()
    await db.refresh(guarantee)
    
    return success_response(
        data=GuaranteeResponseDto.model_validate(guarantee).model_dump(mode="json"),
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
    
    return success_response(
        data=GuaranteeResponseDto.model_validate(guarantee).model_dump(mode="json"),
        message=f"Guarantee {id} updated"
    )

@router.get("/{id}/upload-url")
async def get_upload_url(id: str, content_type: str, db: AsyncSession = Depends(get_db)):
    """Generate a presigned URL to upload a guarantee document directly to S3"""
    query = select(GuaranteeModel).where(GuaranteeModel.id == id)
    result = await db.execute(query)
    guarantee = result.scalar_one_or_none()
    
    if not guarantee:
        raise HTTPException(status_code=404, detail="Guarantee not found")
        
    object_name = f"guarantees/{id}/{uuid4().hex}.pdf"
    
    # Generate presigned POST url
    upload_info = s3_service.generate_presigned_post(object_name, content_type)
    
    if not upload_info:
        raise HTTPException(status_code=500, detail="Could not generate upload URL")
        
    return success_response(
        data={
            "presigned_post": upload_info,
            "object_key": object_name
        },
        message="Upload URL generated"
    )
