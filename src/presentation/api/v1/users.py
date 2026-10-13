"""
Users router — /api/v1/users
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.infrastructure.database import get_db
from src.infrastructure.models.user_model import UserModel
from src.application.dtos.response_wrapper import success_response
from src.application.use_cases.auth_use_case import _user_to_response

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", summary="Ambil semua data pengguna aktif")
async def get_users(db: AsyncSession = Depends(get_db)):
    """
    Returns all active users (for PIC dropdowns, Assignees, etc).
    """
    result = await db.execute(select(UserModel).where(UserModel.status == "Active"))
    users = result.scalars().all()
    
    dto_list = [_user_to_response(u).model_dump() for u in users]
    return success_response(data=dto_list, message="Berhasil mengambil data pengguna")
