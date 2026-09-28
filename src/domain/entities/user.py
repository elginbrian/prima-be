"""
User entity - matches prima-fe types/user.ts exactly

FE UserRole: "Super Admin" | "Procurement Manager" | "Procurement Officer" | "Reviewer" | "Vendor"
FE UserStatus: "Active" | "Inactive" | "Suspended"
FE Department: { id: string; name: string }  ← object, NOT string enum
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# Mirrors FE types/core.ts Department interface
@dataclass
class Department:
    id: str
    name: str


# Mirrors FE types/core.ts BaseUser interface
@dataclass
class BaseUser:
    id: str
    name: str


# Mirrors FE types/user.ts User interface
@dataclass
class User:
    id: str
    name: str
    email: str
    role: str               # "Super Admin" | "Procurement Manager" | "Procurement Officer" | "Reviewer" | "Vendor"
    status: str             # "Active" | "Inactive" | "Suspended"
    created_at: datetime
    phone: Optional[str] = None
    department: Optional[Department] = None
    avatar_url: Optional[str] = None
    last_login: Optional[datetime] = None
    # Security fields (never exposed to FE)
    hashed_password: Optional[str] = None


USER_ROLES = ["Super Admin", "Procurement Manager", "Procurement Officer", "Reviewer", "Vendor"]
USER_STATUSES = ["Active", "Inactive", "Suspended"]
