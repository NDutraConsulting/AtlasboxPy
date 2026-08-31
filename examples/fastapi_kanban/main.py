"""Kanban demo: Starlette + SQLite (via SQLAlchemy) backend, plus a static,
DDD-organized frontend — one folder per feature/page, each holding its own
CSS and a {feature}-controller.js that orchestrates {feature}-api.js +
{feature}-ui.js.

Backend layering:

    api-route > controller (validates its own props, decides what a
        failure means) > [services > [libraries, apis, repositories, models]]

Each api_route below is a one-liner: `_call(request, controller.method)`.
`_call` merges the request into a plain `props` dict (via
atlasboxpy_controller's `extract_api_request` — path params, query params,
and the JSON body, path params winning on a collision), passes that
straight to the controller method with no payload object built in the
route, logs the request/response to the traffic log, and converts the
result to a JSONResponse. The controller method is the one place that
validates `props` (via `validate_props`, against the matching model in
models.py) — a route file that never mentions a Pydantic model at all is
the point: read the controller method and its model, not the route, to
know what a call needs.

KanbanController subclasses BaseController, which wraps every public async
method in a try/except at class-definition time: the controller method
itself builds a SuccessResponse/ErrorResponse directly (see
controllers/kanban_controller.py), and BaseController's wrapper is just the
safety net underneath that for whatever KanbanService (or a failed
validate_props call) didn't already translate. There's no gateway object
anywhere in this file.

Run it with:
    pip install -e "packages/atlasboxpy_controller[dev]"   # needs sqlalchemy + aiosqlite
    pip install -e "packages/atlasboxpy_repository"
    uvicorn examples.fastapi_kanban.main:app --reload
(or just ./run.sh from this directory)

Then open http://127.0.0.1:8000/ in a browser. Every request that moves
through the controller is logged to logs/{YYYY-mm-dd}_atlasboxpy_controller.log
— see logging_setup.py.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from atlasboxpy_controller import ErrorResponse, SuccessResponse, ValidationFailedError
from atlasboxpy_controller.fastapi_integration import extract_api_request, to_json_response
from atlasboxpy_controller.responses import build_error_response

from .controllers import KanbanController
from .db import DEFAULT_DB_PATH, SessionFactory, init_db, make_engine, make_session_factory
from .logging_setup import configure_traffic_logging
from .models import SimulateDbErrorRequest
from .db_simulation import set_simulation
from .validation import validate_body

_STATIC_DIR = Path(__file__).parent / "static"
_traffic_log = logging.getLogger("atlasboxpy_controller.traffic")

_ControllerMethod = Callable[[dict[str, Any]], Coroutine[Any, Any, "SuccessResponse[Any] | ErrorResponse"]]


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


def create_app(session_factory: SessionFactory | None = None) -> Starlette:
    """App factory. With no arguments, builds the real SQLite file and
    creates its schema on startup — the production path. Tests pass their
    own `session_factory` (already pointed at a fresh in-memory database
    with its schema already created), for full isolation between tests."""
    owns_engine = session_factory is None
    if session_factory is None:
        engine = make_engine(f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}")
        session_factory = make_session_factory(engine)

    controller = KanbanController(session_factory)

    # Every route below is exactly this: extract props from the request,
    # hand them to a controller method, format the result. No payload
    # object is built here — the controller method validates its own props
    # (see controllers/kanban_controller.py and models.py).

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

    routes = [
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
        # Registered after the API routes so /api/* is matched first — the
        # static mount at "/" would otherwise greedily swallow every path.
        Mount("/", app=StaticFiles(directory=str(_STATIC_DIR), html=True), name="static"),
    ]

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        if owns_engine:
            await init_db(engine)
        yield

    return Starlette(routes=routes, lifespan=lifespan)


configure_traffic_logging()
app = create_app()
