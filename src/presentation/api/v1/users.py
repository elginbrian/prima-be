"""
Users router — /api/v1/users
"""
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.infrastructure.database import get_db
from src.infrastructure.models.user_model import UserModel
from src.application.dtos.auth_schemas import UpdateProfileRequest
from src.application.dtos.response_wrapper import success_response
from src.application.use_cases.auth_use_case import AuthUseCase, _user_to_response
from src.presentation.auth_dependencies import get_current_user

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


@router.put("/me", summary="Perbarui profil pengguna saat ini")
async def update_current_user_profile(
    body: UpdateProfileRequest,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    auth_use_case = AuthUseCase(db)
    updated_user = await auth_use_case.update_profile(user, body)
    return success_response(
        data=updated_user.model_dump(),
        message="Profil berhasil diperbarui",
    )


@router.post("/me/avatar", summary="Unggah foto profil pengguna saat ini")
async def upload_current_user_avatar(
    file: UploadFile = File(...),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    auth_use_case = AuthUseCase(db)
    file_bytes = await file.read()
    updated_user = await auth_use_case.upload_avatar(
        user,
        file_bytes=file_bytes,
        filename=file.filename or "avatar.png",
        content_type=file.content_type,
    )
    return success_response(
        data=updated_user.model_dump(),
        message="Foto profil berhasil diperbarui",
    )
