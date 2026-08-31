from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from atlasboxpy_controller.responses import ErrorResponse, SuccessResponse


def to_json_response(result: SuccessResponse[Any] | ErrorResponse) -> JSONResponse:
    """Convert a SuccessResponse/ErrorResponse envelope into a
    fastapi.responses.JSONResponse. `response_code` — set at the controller,
    the same value an in-process caller (an agent, a worker, a test) already
    reads directly off the envelope with no HTTP round trip — IS the HTTP
    status here too: one number instead of a separate REST-only mapping to
    keep in sync with it."""
    return JSONResponse(status_code=result.response_code, content=result.model_dump(mode="json"))
