"""Typed application errors -> RFC 7807 problem+json (always carrying the correlation id)."""
from __future__ import annotations


class AppError(Exception):
    status = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, details=None, headers: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers or {}


class ValidationFailed(AppError): status, code = 400, "VALIDATION_ERROR"
class Unauthenticated(AppError): status, code = 401, "UNAUTHENTICATED"
class Forbidden(AppError): status, code = 403, "FORBIDDEN"
class NotFound(AppError): status, code = 404, "NOT_FOUND"
class Conflict(AppError): status, code = 409, "CONFLICT"
class PayloadTooLarge(AppError): status, code = 413, "PAYLOAD_TOO_LARGE"
class Unprocessable(AppError): status, code = 422, "UNPROCESSABLE"
class InjectionBlocked(AppError): status, code = 422, "PROMPT_INJECTION_BLOCKED"
class RateLimited(AppError): status, code = 429, "RATE_LIMITED"
class DependencyUnavailable(AppError): status, code = 503, "DEPENDENCY_UNAVAILABLE"
