"""
Auth router — /api/v1/auth

Endpoints:
  POST /auth/login      ← email + password
  POST /auth/register   ← name + email + password
  POST /auth/refresh    ← refresh_token
  GET  /auth/me         ← returns current user from Bearer token
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos.auth_schemas import LoginRequest, RegisterRequest, RefreshTokenRequest
from src.application.dtos.response_wrapper import success_response
from src.application.use_cases.auth_use_case import AuthUseCase, _user_to_response
from src.infrastructure.database import get_db
from src.infrastructure.models.user_model import UserModel
from src.presentation.auth_dependencies import get_current_user, get_current_user_payload  # noqa: F401 (re-export)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", summary="Login dengan email dan password")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Login flow dari prima-fe AuthPage (mode='login'):
    - Fields: email, password
    - Returns: access_token, refresh_token, user object
    """
    auth_use_case = AuthUseCase(db)
    token_data = await auth_use_case.login(body)
    return success_response(
        data=token_data.model_dump(),
        message="Login berhasil",
    )


@router.post("/register", summary="Daftar akun baru")
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Register flow dari prima-fe AuthPage (mode='register'):
    - Fields: name, email, password
    - Default role: Procurement Officer (admin can upgrade later)
    - Returns: user object
    """
    auth_use_case = AuthUseCase(db)
    user = await auth_use_case.register(body)
    return success_response(
        data=user.model_dump(),
        message="Akun berhasil dibuat. Silakan login.",
        code=201,
    )


@router.post("/refresh", summary="Refresh access token")
async def refresh(body: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh_token for a new token pair"""
    auth_use_case = AuthUseCase(db)
    token_data = await auth_use_case.refresh(body.refresh_token)
    return success_response(
        data=token_data.model_dump(),
        message="Token diperbarui",
    )


@router.get("/me", summary="Ambil data user yang sedang login")
async def me(user: UserModel = Depends(get_current_user)):
    """Returns current authenticated user from JWT Bearer token"""
    return success_response(data=_user_to_response(user).model_dump(), message="OK")
