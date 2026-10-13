"""
Authentication / authorization dependencies shared by all routers.

- get_current_user_payload : validates the Bearer access token, returns the JWT payload
- get_current_user         : loads the user, rejects unknown / inactive accounts
- require_roles(*roles)    : RBAC guard factory
"""
from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.exceptions import ForbiddenException, UnauthorizedException
from src.infrastructure.database import get_db
from src.infrastructure.models.user_model import UserModel
from src.infrastructure.security.jwt import decode_token

# auto_error=False so a missing header yields our 401 (FE refresh logic keys off 401, not 403).
bearer_scheme = HTTPBearer(auto_error=False)

ROLE_SUPER_ADMIN = "Super Admin"
ROLE_MANAGER = "Procurement Manager"
ROLE_OFFICER = "Procurement Officer"


def get_current_user_payload(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Validates the Bearer access token and returns the JWT payload."""
    if credentials is None:
        raise UnauthorizedException("Autentikasi diperlukan")
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise UnauthorizedException("Token tidak valid atau sudah kedaluwarsa")
    if payload.get("type") != "access":
        raise UnauthorizedException("Token tidak valid")
    return payload


async def get_current_user(
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    """Loads the authenticated user and makes sure the account is still active."""
    result = await db.execute(select(UserModel).where(UserModel.id == payload.get("sub")))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedException("Pengguna tidak ditemukan")
    if user.status != "Active":
        raise UnauthorizedException("Akun Anda tidak aktif. Hubungi administrator.")
    return user


def require_roles(*allowed_roles: str):
    """Dependency factory: only users whose role is in `allowed_roles` may proceed."""

    async def _guard(user: UserModel = Depends(get_current_user)) -> UserModel:
        if user.role not in allowed_roles:
            raise ForbiddenException("Anda tidak memiliki akses untuk tindakan ini")
        return user

    return _guard
