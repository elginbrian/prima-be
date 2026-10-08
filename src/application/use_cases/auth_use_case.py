"""
Auth Use Case — login, register, refresh token

Currently uses in-memory store since DB/ORM is not yet wired.
Replace _USER_STORE with a real UserRepository when DB is ready.
"""
from datetime import datetime, timezone
import uuid
from typing import Optional

from src.domain.entities.user import User, Department
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

# ─── Temporary in-memory user store (replace with DB repo) ────────────────────
# Pre-seeded from FE mock users.json so FE mock data works end-to-end
_USER_STORE: dict[str, User] = {
    "budi.santoso@pertamina.com": User(
        id="USR-001",
        name="Budi Santoso",
        email="budi.santoso@pertamina.com",
        phone="+6281234567890",
        role="Procurement Officer",
        department=Department(id="DEPT-IT", name="IT Infrastructure"),
        status="Active",
        created_at=datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
        last_login=datetime(2024, 9, 18, 1, 30, 0, tzinfo=timezone.utc),
        hashed_password=hash_password("password123"),
    ),
    "rina.g@pertamina.com": User(
        id="USR-002",
        name="Rina Gunawan",
        email="rina.g@pertamina.com",
        phone="+6281298765432",
        role="Procurement Manager",
        department=Department(id="DEPT-OPS", name="Operations"),
        status="Active",
        created_at=datetime(2023, 11, 20, 9, 15, 0, tzinfo=timezone.utc),
        hashed_password=hash_password("password123"),
    ),
    "siti.aminah@pertamina.com": User(
        id="USR-006",
        name="Siti Aminah",
        email="siti.aminah@pertamina.com",
        phone="+6287776665554",
        role="Super Admin",
        department=Department(id="DEPT-IT", name="IT Infrastructure"),
        status="Active",
        created_at=datetime(2023, 8, 1, 8, 0, 0, tzinfo=timezone.utc),
        hashed_password=hash_password("password123"),
    ),
    "admin@prima.id": User(
        id="USR-ADMIN",
        name="Administrator",
        email="admin@prima.id",
        phone="+628111222333",
        role="Super Admin",
        department=Department(id="DEPT-IT", name="IT Infrastructure"),
        status="Active",
        created_at=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
        hashed_password=hash_password("admin123"),
    ),
}


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at.isoformat(),
        phone=user.phone,
        department=DepartmentSchema(id=user.department.id, name=user.department.name) if user.department else None,
        avatar_url=user.avatar_url,
        last_login=user.last_login.isoformat() if user.last_login else None,
    )


class AuthUseCase:
    """Handles login, register, and token refresh"""

    def login(self, req: LoginRequest) -> TokenResponse:
        user = _USER_STORE.get(req.email.lower())
        if not user or not user.hashed_password:
            raise UnauthorizedException("Email atau kata sandi salah")
        if not verify_password(req.password, user.hashed_password):
            raise UnauthorizedException("Email atau kata sandi salah")
        if user.status != "Active":
            raise UnauthorizedException("Akun Anda tidak aktif. Hubungi administrator.")

        # Update last_login
        user.last_login = datetime.now(timezone.utc)

        token_data = {"sub": user.id, "email": user.email, "role": user.role}
        return TokenResponse(
            access_token=create_access_token(token_data),
            refresh_token=create_refresh_token(token_data),
            user=_user_to_response(user),
        )

    def register(self, req: RegisterRequest) -> UserResponse:
        email_lower = req.email.lower()
        if email_lower in _USER_STORE:
            raise AlreadyExistsException("Email sudah terdaftar")

        new_user = User(
            id=f"USR-{str(uuid.uuid4())[:8].upper()}",
            name=req.name,
            email=email_lower,
            role="Procurement Officer",   # Default role for self-registration
            status="Active",
            created_at=datetime.now(timezone.utc),
            hashed_password=hash_password(req.password),
        )
        _USER_STORE[email_lower] = new_user
        return _user_to_response(new_user)

    def refresh(self, refresh_token: str) -> TokenResponse:
        from jose import JWTError
        try:
            payload = decode_token(refresh_token)
            if payload.get("type") != "refresh":
                raise UnauthorizedException("Token tidak valid")
            user_id: str = payload.get("sub")
            user = next((u for u in _USER_STORE.values() if u.id == user_id), None)
            if not user:
                raise UnauthorizedException("Pengguna tidak ditemukan")
            token_data = {"sub": user.id, "email": user.email, "role": user.role}
            return TokenResponse(
                access_token=create_access_token(token_data),
                refresh_token=create_refresh_token(token_data),
                user=_user_to_response(user),
            )
        except JWTError:
            raise UnauthorizedException("Token tidak valid atau sudah kedaluwarsa")


auth_use_case = AuthUseCase()
