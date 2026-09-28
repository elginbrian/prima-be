"""
User entity - mirrors prima-fe types/user.ts and types/core.ts BaseUser
"""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "Admin"
    BUYER = "Buyer"
    FPP = "FPP"
    VIEWER = "Viewer"


class Department(str, Enum):
    PENGADAAN = "Pengadaan"
    KEUANGAN = "Keuangan"
    OPERASIONAL = "Operasional"
    LEGAL = "Legal"
    IT = "IT"
    HR = "HR"


@dataclass
class BaseUser:
    id: str
    name: str
    role: UserRole
    department: Department
    avatar: Optional[str] = None


@dataclass
class User(BaseUser):
    email: str = ""
    hashed_password: Optional[str] = None
    is_active: bool = True
