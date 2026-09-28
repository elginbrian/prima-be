"""
Auth router — /api/v1/auth

Endpoints:
  POST /auth/login      ← email + password
  POST /auth/register   ← name + email + password
  POST /auth/refresh    ← refresh_token
  GET  /auth/me         ← returns current user from Bearer token
"""
from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.application.dtos.auth_schemas import LoginRequest, RegisterRequest, RefreshTokenRequest
from src.application.dtos.response_wrapper import success_response, error_response
from src.application.use_cases.auth_use_case import auth_use_case
from src.domain.exceptions import UnauthorizedException
from src.infrastructure.security.jwt import decode_token

router = APIRouter(prefix="/auth", tags=["Authentication"])
bearer_scheme = HTTPBearer()


def get_current_user_payload(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    """Dependency: validates Bearer token and returns JWT payload"""
    from jose import JWTError
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise UnauthorizedException("Token tidak valid")
        return payload
    except JWTError:
        raise UnauthorizedException("Token tidak valid atau sudah kedaluwarsa")


@router.post("/login", summary="Login dengan email dan password")
async def login(body: LoginRequest):
    """
    Login flow dari prima-fe AuthPage (mode='login'):
    - Fields: email, password
    - Returns: access_token, refresh_token, user object
    """
    token_data = auth_use_case.login(body)
    return success_response(
        data=token_data.model_dump(),
        message="Login berhasil",
    )


@router.post("/register", summary="Daftar akun baru")
async def register(body: RegisterRequest):
    """
    Register flow dari prima-fe AuthPage (mode='register'):
    - Fields: name, email, password (confirmPassword validated on FE, NOT sent to BE)
    - Default role: Procurement Officer (admin can upgrade later)
    - Returns: user object
    """
    user = auth_use_case.register(body)
    return success_response(
        data=user.model_dump(),
        message="Akun berhasil dibuat. Silakan login.",
        code=201,
    )


@router.post("/refresh", summary="Refresh access token")
async def refresh(body: RefreshTokenRequest):
    """Exchange a valid refresh_token for a new token pair"""
    token_data = auth_use_case.refresh(body.refresh_token)
    return success_response(
        data=token_data.model_dump(),
        message="Token diperbarui",
    )


@router.get("/me", summary="Ambil data user yang sedang login")
async def me(payload: dict = Depends(get_current_user_payload)):
    """Returns current authenticated user from JWT Bearer token"""
    from src.application.use_cases.auth_use_case import _USER_STORE, _user_to_response
    user_id: str = payload.get("sub")
    user = next((u for u in _USER_STORE.values() if u.id == user_id), None)
    if not user:
        raise UnauthorizedException("Pengguna tidak ditemukan")
    return success_response(data=_user_to_response(user).model_dump(), message="OK")
