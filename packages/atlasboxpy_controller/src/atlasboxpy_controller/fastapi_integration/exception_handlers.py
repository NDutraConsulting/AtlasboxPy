from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from atlasboxpy_controller.exceptions import status_for_code
from atlasboxpy_controller.responses import ErrorResponse, SuccessResponse


def to_json_response(result: SuccessResponse[Any] | ErrorResponse) -> JSONResponse:
    """Convert a SuccessResponse/ErrorResponse envelope into a
    fastapi.responses.JSONResponse with the correct HTTP status: 200 for
    success, the DomainError's mapped status (P1-T3) for errors."""
    if isinstance(result, SuccessResponse):
        return JSONResponse(status_code=200, content=result.model_dump(mode="json"))
    mapping = status_for_code(result.error.code)
    return JSONResponse(status_code=mapping.http_status, content=result.model_dump(mode="json"))
