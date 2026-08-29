from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from validator_gateway.exceptions import DomainError

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    status: Literal["success"] = "success"
    data: T


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error: ErrorDetail


def build_error_response(exc: DomainError) -> ErrorResponse:
    return ErrorResponse(
        error=ErrorDetail(code=exc.code, message=exc.message, details=exc.details)
    )
