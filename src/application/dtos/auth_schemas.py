"""
Auth DTOs — request/response schemas matching prima-fe AuthPage.tsx fields

Login fields:  email, password
Register fields: name, email, password, (confirmPassword validated on FE only)

NOTE: confirmPassword is NOT sent to BE — FE validates match before submitting.
"""
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional


# ─── REQUEST ─────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# ─── RESPONSE ────────────────────────────────────────────────────────────────

class DepartmentSchema(BaseModel):
    id: str
    name: str


class UserResponse(BaseModel):
    """
    Mirrors prima-fe types/user.ts User interface exactly.
    Fields: id, name, email, phone?, role, department?, status, avatarUrl?, lastLogin?, createdAt
    """
    id: str
    name: str
    email: str
    role: str
    status: str
    created_at: str
    phone: Optional[str] = None
    department: Optional[DepartmentSchema] = None
    avatar_url: Optional[str] = None
    last_login: Optional[str] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class LoginResponse(BaseModel):
    success: bool
    message: str
    data: TokenResponse
    code: int = 200


class RegisterResponse(BaseModel):
    success: bool
    message: str
    data: UserResponse
    code: int = 201
