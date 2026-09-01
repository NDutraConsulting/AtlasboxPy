"""Minimal HTTP routing — forwards clean requests to KanbanController,
nothing else. `build_routes(controller)` is the only thing main.py calls
from here; this file has no idea how the controller, its service, or
anything under infrastructure/ works, only that calling a controller
method returns a SuccessResponse/ErrorResponse.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from atlasboxpy_controller import ErrorResponse, SuccessResponse, ValidationFailedError
from atlasboxpy_controller.fastapi_integration import (
    extract_api_request,
    to_json_response,
)
from atlasboxpy_controller.responses import build_error_response
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..controllers import KanbanController
from ..infrastructure.database.db_connections.db_simulation import set_simulation
from ..validation import validate_body

_traffic_log = logging.getLogger("atlasboxpy_controller.traffic")

_ControllerMethod = Callable[[dict[str, Any]], Coroutine[Any, Any, "SuccessResponse[Any] | ErrorResponse"]]


class SimulateDbErrorRequest(BaseModel):
    """Body shape for the debug-only /api/debug/db-connection route below
    — not a KanbanController request contract (see
    controllers/kanban_controller.py for those), since this route
    deliberately bypasses the controller entirely. Defined here, next to
    its one and only caller, rather than in a shared models module."""

    enabled: bool
    mode: str = "error"  # "error" or "timeout"


def _error_response(exc: ValidationFailedError) -> JSONResponse:
    return to_json_response(build_error_response(exc))


async def _call(request: Request, method: _ControllerMethod) -> JSONResponse:
    """Extracts `props` from the request, calls a KanbanController method
    with it, logs the request/response to the traffic log, and converts
    the result to a JSONResponse. Every request that reaches a controller
    passes through here — the one place prop-extraction and logging live,
    instead of every route repeating them."""
    props = await extract_api_request(request)
    result: SuccessResponse[Any] | ErrorResponse = await method(props)
    status = "success" if isinstance(result, SuccessResponse) else result.error.code
    _traffic_log.info(
        "source=%s method=%s status=%s request=%s response=%s",
        json.dumps(
            {"url": request.url.path, "method": request.method, "caller_type": "api_route"}
        ),
        method.__name__,
        status,
        json.dumps(props),
        json.dumps(result.model_dump(mode="json")),
    )
    return to_json_response(result)


def build_routes(controller: KanbanController) -> list[Route]:
    """Every route below is exactly this: extract props from the request,
    hand them to a controller method, format the result. No payload
    object is built here — the controller method validates its own props
    (see controllers/kanban_controller.py)."""

    async def create_board(request: Request) -> JSONResponse:
        return await _call(request, controller.create_board)

    async def list_boards(request: Request) -> JSONResponse:
        return await _call(request, controller.list_boards)

    async def get_board(request: Request) -> JSONResponse:
        return await _call(request, controller.get_board)

    async def delete_board(request: Request) -> JSONResponse:
        return await _call(request, controller.delete_board)

    async def add_column(request: Request) -> JSONResponse:
        return await _call(request, controller.add_column)

    async def delete_column(request: Request) -> JSONResponse:
        return await _call(request, controller.delete_column)

    async def create_card(request: Request) -> JSONResponse:
        return await _call(request, controller.create_card)

    async def update_card(request: Request) -> JSONResponse:
        return await _call(request, controller.update_card)

    async def move_card(request: Request) -> JSONResponse:
        return await _call(request, controller.move_card)

    async def delete_card(request: Request) -> JSONResponse:
        return await _call(request, controller.delete_card)

    async def set_db_connection_simulation(request: Request) -> JSONResponse:
        """Test-only utility — deliberately NOT routed through the
        controller, unlike every route above. Flipping a flag isn't domain
        logic, so there's no controller method for it; this exists purely
        so you can simulate "the database is down" or "the database is
        slow" to exercise those failure paths on demand, e.g.:

            curl -X POST localhost:8000/api/debug/db-connection \\
                -d '{"enabled": true, "mode": "error"}'
        """
        try:
            payload = await validate_body(request, SimulateDbErrorRequest)
        except ValidationFailedError as exc:
            return _error_response(exc)
        mode = payload.mode if payload.enabled else None
        await set_simulation(mode)
        return JSONResponse({"simulate_db_error": payload.enabled, "mode": mode})

    return [
        Route("/api/boards", create_board, methods=["POST"]),
        Route("/api/boards", list_boards, methods=["GET"]),
        Route("/api/boards/{board_id}", get_board, methods=["GET"]),
        Route("/api/boards/{board_id}", delete_board, methods=["DELETE"]),
        Route("/api/boards/{board_id}/columns", add_column, methods=["POST"]),
        Route("/api/boards/{board_id}/columns/{column_id}", delete_column, methods=["DELETE"]),
        Route("/api/boards/{board_id}/cards", create_card, methods=["POST"]),
        Route("/api/cards/{card_id}", update_card, methods=["PATCH"]),
        Route("/api/cards/{card_id}/move", move_card, methods=["POST"]),
        Route("/api/cards/{card_id}", delete_card, methods=["DELETE"]),
        Route("/api/debug/db-connection", set_db_connection_simulation, methods=["POST"]),
    ]
