"""
SQLAlchemy ORM model for User
"""
from sqlalchemy import Column, String, DateTime
from datetime import datetime, timezone
from src.infrastructure.database import Base


class UserModel(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, nullable=False, default="Procurement Officer")
    status = Column(String, nullable=False, default="Active")
    phone = Column(String, nullable=True)
    
    # Department flat fields
    department_id = Column(String, nullable=True)
    department_name = Column(String, nullable=True)
    
    avatar_url = Column(String, nullable=True)
    
    # Security
    hashed_password = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime(timezone=True), nullable=True)
