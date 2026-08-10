"""Centralized application exceptions.

All domain-specific errors inherit from AppException, which carries
an HTTP status code and a machine-readable error code.  The global
exception handler in main.py converts these to JSON responses.
"""

from fastapi import HTTPException


class AppException(HTTPException):
    """Base application exception with a machine-readable error code."""

    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


class ResourceNotFound(AppException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(404, "not_found", f"{resource} not found")


class OwnershipError(AppException):
    def __init__(self):
        super().__init__(403, "forbidden", "You do not have access to this resource")


class ValidationError(AppException):
    def __init__(self, detail: str):
        super().__init__(400, "validation_error", detail)


class FileTooLarge(AppException):
    def __init__(self, max_mb: int):
        super().__init__(400, "file_too_large", f"File too large. Max {max_mb}MB")


class UnsupportedFileType(AppException):
    def __init__(self, filename: str):
        super().__init__(400, "unsupported_file_type", f"Unsupported file type: {filename}")


class RateLimitExceeded(AppException):
    def __init__(self):
        super().__init__(429, "rate_limit_exceeded", "Too many requests. Please try again later.")
