from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

# Every DomainError subclass's `code` is tracked here the moment the class is
# defined (via __init_subclass__ below), independent of whether it has its
# own distinct entry in _STATUS_MAP. This matters because a subclass like
# AlreadyExistsError deliberately has NO explicit _STATUS_MAP entry — it
# inherits ConflictError's mapping via the MRO walk in resolve_status() — but
# "already_exists" must still be a known code for known_codes()/is_retryable()/
# status_for_code(), or policy validation and status lookups would wrongly
# treat it as unrecognized and fall back to a generic 500.
_CODE_TO_TYPE: dict[str, type[DomainError]] = {}


class DomainError(Exception):
    code: str = "domain_error"
    default_message: str = "A domain error occurred."
    retryable: bool = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _CODE_TO_TYPE[cls.code] = cls

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


_CODE_TO_TYPE[DomainError.code] = DomainError


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


class TimedOutError(DomainError):
    code = "timeout"
    default_message = "The operation timed out."


class OutOfMemoryError(DomainError):
    code = "out_of_memory"
    default_message = "The operation ran out of memory."
    retryable = False


class StackOverflowError(DomainError):
    code = "stack_overflow"
    default_message = "The operation exceeded the maximum recursion depth."
    retryable = False


class ResponseStatus(str, Enum):
    """Transport-agnostic status label carried in the response envelope
    itself (SuccessResponse.status / ErrorResponse.status) — separate from
    the http_status/grpc_status a StatusMapping also carries.

    The point: a caller reading a response in-process (an agent calling a
    controller method directly, a worker, a test) gets a self-describing
    result without ever touching HTTP — no handshake, no status-code table
    to keep in sync with a transport layer. `status` says what kind of
    thing happened; `response_code` (see StatusMapping.response_code) is
    the numeric counterpart for callers that want to switch on an int.
    The REST adapter (to_json_response) still sets a real HTTP status too —
    this doesn't replace that, it's what the envelope carries independent
    of it.
    """

    SUCCESS = "success"
    EVENT_FIRED = "event-fired"
    ERROR = "error"
    TIMEOUT = "timeout"
    NOT_FOUND = "not-found"
    EXCEPTION = "exception"
    API_ERROR = "api-error"
    OUT_OF_MEMORY = "out-of-memory"
    STACK_OVERFLOW = "stack-overflow"


@dataclass(frozen=True)
class StatusMapping:
    http_status: int
    grpc_status: str
    response_code: int
    response_status: ResponseStatus

    def __post_init__(self) -> None:
        if not (100 <= self.response_code <= 999):
            raise ValueError(f"response_code must be in [100, 999], got {self.response_code}")


_STATUS_MAP: dict[type[DomainError], StatusMapping] = {
    DomainError: StatusMapping(500, "UNKNOWN", 500, ResponseStatus.EXCEPTION),
    ValidationFailedError: StatusMapping(422, "INVALID_ARGUMENT", 422, ResponseStatus.ERROR),
    NotFoundError: StatusMapping(404, "NOT_FOUND", 404, ResponseStatus.NOT_FOUND),
    ConflictError: StatusMapping(409, "ALREADY_EXISTS", 409, ResponseStatus.ERROR),
    PermissionDeniedError: StatusMapping(403, "PERMISSION_DENIED", 403, ResponseStatus.ERROR),
    UnauthenticatedError: StatusMapping(401, "UNAUTHENTICATED", 401, ResponseStatus.ERROR),
    PreconditionFailedError: StatusMapping(412, "FAILED_PRECONDITION", 412, ResponseStatus.ERROR),
    RateLimitedError: StatusMapping(429, "RESOURCE_EXHAUSTED", 429, ResponseStatus.ERROR),
    UnprocessableError: StatusMapping(422, "FAILED_PRECONDITION", 422, ResponseStatus.ERROR),
    UpstreamServiceError: StatusMapping(502, "UNAVAILABLE", 502, ResponseStatus.API_ERROR),
    TimedOutError: StatusMapping(504, "DEADLINE_EXCEEDED", 504, ResponseStatus.TIMEOUT),
    OutOfMemoryError: StatusMapping(500, "RESOURCE_EXHAUSTED", 507, ResponseStatus.OUT_OF_MEMORY),
    StackOverflowError: StatusMapping(500, "INTERNAL", 508, ResponseStatus.STACK_OVERFLOW),
}

def register_status_mapping(
    exc_type: type[DomainError],
    http_status: int,
    grpc_status: str,
    *,
    response_code: int | None = None,
    response_status: ResponseStatus = ResponseStatus.ERROR,
) -> None:
    """Register a StatusMapping for a custom DomainError subclass.

    `response_code`/`response_status` are optional so existing 2-arg call
    sites (http_status, grpc_status) keep working: response_code defaults
    to http_status (already in the valid [100, 999] range for any real HTTP
    status), response_status defaults to the generic ResponseStatus.ERROR.
    """
    resolved_response_code = response_code if response_code is not None else http_status
    _STATUS_MAP[exc_type] = StatusMapping(
        http_status, grpc_status, resolved_response_code, response_status
    )
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
    return set(_CODE_TO_TYPE)
