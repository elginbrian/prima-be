"""
Auth Use Case — login, register, refresh token
"""
from datetime import datetime, timezone
import io
import re
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from src.infrastructure.models.user_model import UserModel
from src.infrastructure.models.procurement_model import ProcurementRequestModel
from src.infrastructure.models.document_model import DocumentModel
from src.infrastructure.models.guarantee_model import GuaranteeModel
from src.infrastructure.storage.s3_service import s3_service
from src.domain.exceptions import AlreadyExistsException, UnauthorizedException, NotFoundException
from src.infrastructure.security.jwt import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from src.application.dtos.auth_schemas import (
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserResponse,
    TokenResponse,
    DepartmentSchema,
)


def _user_to_response(user: UserModel) -> UserResponse:
    dept = None
    if user.department_id and user.department_name:
        dept = DepartmentSchema(id=user.department_id, name=user.department_name)
    elif user.department_name:
        dept = DepartmentSchema(id="DEPT-GEN", name=user.department_name)

    resolved_avatar = user.avatar_url
    if resolved_avatar and not (
        resolved_avatar.startswith("http://")
        or resolved_avatar.startswith("https://")
        or resolved_avatar.startswith("data:")
        or resolved_avatar.startswith("/uploads/")
    ):
        resolved_avatar = s3_service.generate_presigned_url(resolved_avatar)

    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at.isoformat() if getattr(user, 'created_at', None) else datetime.now(timezone.utc).isoformat(),
        phone=user.phone,
        department=dept,
        avatar_url=resolved_avatar,
        last_login=user.last_login.isoformat() if getattr(user, 'last_login', None) else None,
    )


class AuthUseCase:
    """Handles login, register, and token refresh using DB"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def login(self, req: LoginRequest) -> TokenResponse:
        email_lower = req.email.lower()
        result = await self.db.execute(select(UserModel).where(UserModel.email == email_lower))
        user = result.scalar_one_or_none()
        
        if not user or not user.hashed_password:
            raise UnauthorizedException("Email atau kata sandi salah")
        if not verify_password(req.password, user.hashed_password):
            raise UnauthorizedException("Email atau kata sandi salah")
        if user.status != "Active":
            raise UnauthorizedException("Akun Anda tidak aktif. Hubungi administrator.")

        # Update last_login
        user.last_login = datetime.now(timezone.utc)
        await self.db.commit()

        token_data = {"sub": user.id, "email": user.email, "role": user.role}
        return TokenResponse(
            access_token=create_access_token(token_data),
            refresh_token=create_refresh_token(token_data),
            user=_user_to_response(user),
        )

    async def register(self, req: RegisterRequest) -> UserResponse:
        email_lower = req.email.lower()
        result = await self.db.execute(select(UserModel).where(UserModel.email == email_lower))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise AlreadyExistsException("Email sudah terdaftar")

        new_user = UserModel(
            id=f"USR-{str(uuid.uuid4())[:8].upper()}",
            name=req.name,
            email=email_lower,
            role="Procurement Officer",   # Default role for self-registration
            status="Active",
            created_at=datetime.now(timezone.utc),
            hashed_password=hash_password(req.password),
        )
        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)
        
        return _user_to_response(new_user)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        from jose import JWTError
        try:
            payload = decode_token(refresh_token)
            if payload.get("type") != "refresh":
                raise UnauthorizedException("Token tidak valid")
            user_id: str = payload.get("sub")
            
            result = await self.db.execute(select(UserModel).where(UserModel.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                raise UnauthorizedException("Pengguna tidak ditemukan")
            if user.status != "Active":
                raise UnauthorizedException("Akun Anda tidak aktif. Hubungi administrator.")
                
            token_data = {"sub": user.id, "email": user.email, "role": user.role}
            return TokenResponse(
                access_token=create_access_token(token_data),
                refresh_token=create_refresh_token(token_data),
                user=_user_to_response(user),
            )
        except JWTError:
            raise UnauthorizedException("Token tidak valid atau sudah kedaluwarsa")

    async def update_profile(self, user: UserModel, req: UpdateProfileRequest) -> UserResponse:
        if req.email is not None:
            email_lower = req.email.lower().strip()
            if email_lower != user.email.lower():
                existing = await self.db.execute(
                    select(UserModel).where(UserModel.email == email_lower, UserModel.id != user.id)
                )
                if existing.scalar_one_or_none():
                    raise AlreadyExistsException("Email sudah digunakan oleh pengguna lain")
                user.email = email_lower

        name_changed = False
        if req.name is not None and req.name.strip():
            new_name = req.name.strip()
            if new_name != user.name:
                user.name = new_name
                name_changed = True

        if req.phone is not None:
            user.phone = req.phone.strip() or None

        if req.department_id is not None:
            user.department_id = req.department_id.strip() or None

        if req.department_name is not None:
            dept_name = req.department_name.strip()
            user.department_name = dept_name or None
            if dept_name and not user.department_id:
                dept_map = {
                    "Procurement & General Support": "DEPT-PROC",
                    "IT Infrastructure": "DEPT-IT",
                    "Operations": "DEPT-OPS",
                    "Human Resources": "DEPT-HR",
                    "General Affairs": "DEPT-GA",
                }
                user.department_id = dept_map.get(dept_name, "DEPT-GEN")

        if req.role is not None and req.role.strip():
            user.role = req.role.strip()

        if req.avatar_url is not None:
            user.avatar_url = req.avatar_url.strip() or None

        if name_changed:
            await self.db.execute(
                update(ProcurementRequestModel)
                .where(ProcurementRequestModel.pic_id == user.id)
                .values(pic_name=user.name)
            )
            await self.db.execute(
                update(DocumentModel)
                .where(DocumentModel.pic_id == user.id)
                .values(pic_name=user.name)
            )
            await self.db.execute(
                update(GuaranteeModel)
                .where(GuaranteeModel.pic_id == user.id)
                .values(pic_name=user.name)
            )

        await self.db.commit()
        await self.db.refresh(user)
        return _user_to_response(user)

    async def upload_avatar(
        self,
        user: UserModel,
        file_bytes: bytes,
        filename: str,
        content_type: Optional[str] = None,
    ) -> UserResponse:
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename or "avatar.png")
        object_key = f"avatars/{user.id}/{uuid.uuid4().hex[:8]}_{safe_name}"
        saved_key = s3_service.upload_file(
            io.BytesIO(file_bytes),
            object_key,
            content_type=content_type or "image/png",
        )
        user.avatar_url = saved_key
        await self.db.commit()
        await self.db.refresh(user)
        return _user_to_response(user)
