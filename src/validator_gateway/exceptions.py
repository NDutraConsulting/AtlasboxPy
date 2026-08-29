from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class DomainError(Exception):
    code: str = "domain_error"
    default_message: str = "A domain error occurred."
    retryable: bool = True

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details: dict[str, Any] = details or {}
        self.cause = cause
        super().__init__(self.message)


class ValidationFailedError(DomainError):
    code = "validation_failed"
    default_message = "Validation failed."
    retryable = False


class NotFoundError(DomainError):
    code = "not_found"
    default_message = "Resource not found."


class ConflictError(DomainError):
    code = "conflict"
    default_message = "Conflict with current state."


class AlreadyExistsError(ConflictError):
    code = "already_exists"
    default_message = "Resource already exists."


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    default_message = "Permission denied."
    retryable = False


class UnauthenticatedError(DomainError):
    code = "unauthenticated"
    default_message = "Authentication required."
    retryable = False


class PreconditionFailedError(DomainError):
    code = "precondition_failed"
    default_message = "Precondition failed."


class RateLimitedError(DomainError):
    code = "rate_limited"
    default_message = "Rate limit exceeded."


class UnprocessableError(DomainError):
    code = "unprocessable"
    default_message = "Request could not be processed."


class UpstreamServiceError(DomainError):
    code = "upstream_error"
    default_message = "An upstream service failed."


@dataclass(frozen=True)
class StatusMapping:
    http_status: int
    grpc_status: str


_STATUS_MAP: dict[type[DomainError], StatusMapping] = {
    DomainError: StatusMapping(500, "UNKNOWN"),
    ValidationFailedError: StatusMapping(422, "INVALID_ARGUMENT"),
    NotFoundError: StatusMapping(404, "NOT_FOUND"),
    ConflictError: StatusMapping(409, "ALREADY_EXISTS"),
    PermissionDeniedError: StatusMapping(403, "PERMISSION_DENIED"),
    UnauthenticatedError: StatusMapping(401, "UNAUTHENTICATED"),
    PreconditionFailedError: StatusMapping(412, "FAILED_PRECONDITION"),
    RateLimitedError: StatusMapping(429, "RESOURCE_EXHAUSTED"),
    UnprocessableError: StatusMapping(422, "FAILED_PRECONDITION"),
    UpstreamServiceError: StatusMapping(502, "UNAVAILABLE"),
}

_KNOWN_CODES: set[str] = {exc_type.code for exc_type in _STATUS_MAP}
_CODE_TO_TYPE: dict[str, type[DomainError]] = {
    exc_type.code: exc_type for exc_type in _STATUS_MAP
}


def register_status_mapping(
    exc_type: type[DomainError], http_status: int, grpc_status: str
) -> None:
    _STATUS_MAP[exc_type] = StatusMapping(http_status, grpc_status)
    _KNOWN_CODES.add(exc_type.code)
    _CODE_TO_TYPE[exc_type.code] = exc_type


def is_retryable(code: str) -> bool:
    """Look up the `retryable` flag (P1-T5) for a known DomainError code.

    Used by the recovery policy loader (Phase 5) to reject RETRY steps
    configured against a code that can never succeed on retry.
    """
    try:
        return _CODE_TO_TYPE[code].retryable
    except KeyError:
        raise KeyError(f"Unknown DomainError code: {code!r}") from None


def resolve_status(exc: DomainError) -> StatusMapping:
    for klass in type(exc).__mro__:
        if klass in _STATUS_MAP:
            return _STATUS_MAP[klass]
    return _STATUS_MAP[DomainError]


def status_for_code(code: str) -> StatusMapping:
    """Same lookup as resolve_status(), but keyed by `code` string instead of
    an exception instance — for transport adapters (e.g. to_json_response)
    that only have an already-built ErrorResponse, not the original
    exception."""
    exc_type = _CODE_TO_TYPE.get(code, DomainError)
    return resolve_status(exc_type())


def known_codes() -> set[str]:
    return set(_KNOWN_CODES)
