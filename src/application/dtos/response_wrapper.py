"""
Application Layer DTOs - Response wrappers (mirrors brian-be pattern)
"""
from typing import Any, Optional
from pydantic import BaseModel


class BaseResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None
    code: int = 200


def success_response(data: Any = None, message: str = "Success", code: int = 200) -> dict:
    return {
        "success": True,
        "message": message,
        "data": data,
        "code": code,
    }


def error_response(message: str, code: int = 500, data: Any = None) -> dict:
    return {
        "success": False,
        "message": message,
        "data": data,
        "code": code,
    }
