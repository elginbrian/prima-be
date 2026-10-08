from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import uuid4

from src.infrastructure.database import get_db
from src.infrastructure.models.deadline_model import DeadlineModel
from src.application.dtos.response_wrapper import success_response
from src.application.dtos.deadline_dto import DeadlineCreateDto, DeadlineUpdateDto, DeadlineResponseDto

router = APIRouter(prefix="/deadlines", tags=["Deadlines - D4 SLA"])


@router.get("")
async def get_deadlines(request_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Get all deadlines/SLA (Modul D4). Optionally filter by request_id."""
    query = select(DeadlineModel)
    if request_id:
        query = query.where(DeadlineModel.request_id == request_id)
        
    result = await db.execute(query)
    deadlines = result.scalars().all()
    
    data = [DeadlineResponseDto.model_validate(d).model_dump(mode="json") for d in deadlines]
    return success_response(data=data, message="Deadlines fetched")


@router.get("/{id}")
async def get_deadline_by_id(id: str, db: AsyncSession = Depends(get_db)):
    query = select(DeadlineModel).where(DeadlineModel.id == id)
    result = await db.execute(query)
    deadline = result.scalar_one_or_none()
    
    if not deadline:
        raise HTTPException(status_code=404, detail="Deadline not found")
        
    data = DeadlineResponseDto.model_validate(deadline).model_dump(mode="json")
    return success_response(data=data, message=f"Deadline {id} fetched")


@router.post("")
async def add_deadline(payload: DeadlineCreateDto, db: AsyncSession = Depends(get_db)):
    """Add a new SLA deadline"""
    new_id = f"D-{uuid4().hex[:8].upper()}"
    deadline = DeadlineModel(id=new_id, **payload.model_dump())
    db.add(deadline)
    await db.commit()
    await db.refresh(deadline)
    
    data = DeadlineResponseDto.model_validate(deadline).model_dump(mode="json")
    return success_response(data=data, message="Deadline added", code=201)


@router.patch("/{id}")
async def update_deadline(id: str, payload: DeadlineUpdateDto, db: AsyncSession = Depends(get_db)):
    """Update deadline details or status (On Track / At Risk / Overdue / Selesai)"""
    query = select(DeadlineModel).where(DeadlineModel.id == id)
    result = await db.execute(query)
    deadline = result.scalar_one_or_none()
    
    if not deadline:
        raise HTTPException(status_code=404, detail="Deadline not found")
        
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(deadline, key, value)
        
    await db.commit()
    await db.refresh(deadline)
    
    data = DeadlineResponseDto.model_validate(deadline).model_dump(mode="json")
    return success_response(data=data, message=f"Deadline {id} updated")
