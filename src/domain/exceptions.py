from enum import Enum


class ErrorCode(str, Enum):
    """Domain error codes"""
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class DomainException(Exception):
    """Base domain exception"""
    def __init__(self, message: str, code: ErrorCode = ErrorCode.INTERNAL_ERROR):
        self.message = message
        self.code = code
        super().__init__(self.message)


class NotFoundException(DomainException):
    """Entity not found exception"""
    def __init__(self, message: str = "Entity not found"):
        super().__init__(message, ErrorCode.NOT_FOUND)


class AlreadyExistsException(DomainException):
    """Entity already exists exception"""
    def __init__(self, message: str = "Entity already exists"):
        super().__init__(message, ErrorCode.ALREADY_EXISTS)


class ValidationException(DomainException):
    """Validation exception"""
    def __init__(self, message: str = "Validation error"):
        super().__init__(message, ErrorCode.VALIDATION_ERROR)


class UnauthorizedException(DomainException):
    """Unauthorized exception"""
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, ErrorCode.UNAUTHORIZED)


class ForbiddenException(DomainException):
    """Forbidden exception"""
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, ErrorCode.FORBIDDEN)
