from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from atlasboxpy_controller.exceptions import DomainError, ResponseStatus, resolve_status

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    status: ResponseStatus = ResponseStatus.SUCCESS
    response_code: int = 200
    data: T


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    status: ResponseStatus = ResponseStatus.ERROR
    response_code: int = 500
    error: ErrorDetail


def build_error_response(exc: DomainError) -> ErrorResponse:
    mapping = resolve_status(exc)
    return ErrorResponse(
        status=mapping.response_status,
        response_code=mapping.response_code,
        error=ErrorDetail(code=exc.code, message=exc.message, details=exc.details),
    )
