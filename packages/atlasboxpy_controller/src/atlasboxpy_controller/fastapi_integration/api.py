from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from atlasboxpy_controller.fastapi_integration.exception_handlers import to_json_response
from atlasboxpy_controller.responses import ErrorResponse, SuccessResponse


async def extract_api_request(request: Request) -> dict[str, Any]:
    """Merge a request's query params, JSON body, and path params into one
    flat `props` dict — the single argument a controller method validates
    for itself (see `atlasboxpy_controller.validate_props`), instead of a
    route pre-building a typed payload object for it.

    Path params win on a name collision: they come from the route itself,
    not from anything a caller supplied in the body, so they're the most
    trustworthy source for a given key. A missing or non-JSON/non-object
    body isn't an error here — it becomes an empty dict — because a
    GET/DELETE route with no body needs this to be a no-op; whatever's
    actually required about the request shape is still enforced, once, by
    the controller method's own `validate_props` call.
    """
    try:
        parsed = await request.json()
    except Exception:  # noqa: BLE001 - an empty/non-JSON body just means no body fields
        parsed = None
    body = parsed if isinstance(parsed, dict) else {}
    return {**dict(request.query_params), **body, **dict(request.path_params)}


async def format_json_response(
    result: Awaitable[SuccessResponse[Any] | ErrorResponse],
) -> JSONResponse:
    """Await a controller method call and convert its response envelope
    into a JSONResponse — the other half of a one-line route:

        return await format_json_response(controller.create_card(props))
    """
    return to_json_response(await result)
