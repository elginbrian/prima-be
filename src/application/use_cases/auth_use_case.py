"""
Auth Use Case — login, register, refresh token
"""
from datetime import datetime, timezone
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.infrastructure.models.user_model import UserModel
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
    UserResponse,
    TokenResponse,
    DepartmentSchema,
)


def _user_to_response(user: UserModel) -> UserResponse:
    dept = None
    if user.department_id and user.department_name:
        dept = DepartmentSchema(id=user.department_id, name=user.department_name)
        
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at.isoformat() if getattr(user, 'created_at', None) else datetime.now(timezone.utc).isoformat(),
        phone=user.phone,
        department=dept,
        avatar_url=user.avatar_url,
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
