"""Kanban demo: Starlette + SQLite (via SQLAlchemy) backend, plus a static,
DDD-organized frontend — one folder per feature/page, each holding its own
CSS and a {feature}-controller.js that orchestrates {feature}-api.js +
{feature}-ui.js.

Backend layering:

    api-route > validation > controller (orchestrates services) >
        [services > [libraries, apis, repositories, models]]

Each api_route below: validates its body (validation.py) before touching
anything else, constructs a fresh KanbanValidatorGateway declaring its own
SourceJson (this route's real URL and REST method), and calls
gateway.handle(). The gateway wraps KanbanController, a thin translation
layer over KanbanService — the single service owning the whole board/
column/card aggregate, since those three are one bounded context, not
three independent ones. See services/kanban_service.py.

Run it with:
    pip install -e ".[dev]"   # needs sqlalchemy + aiosqlite, in the dev extra
    uvicorn examples.fastapi_kanban.main:app --reload
(or just ./run.sh from this directory)

Then open http://127.0.0.1:8000/ in a browser. Every request that moves
across the gateway is logged to logs/{YYYY-mm-dd}_validator_gateway.log —
see logging_setup.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from validator_gateway import DomainError, ValidationFailedError
from validator_gateway.fastapi_integration import to_json_response
from validator_gateway.responses import build_error_response

from .db import DEFAULT_DB_PATH, SessionFactory, init_db, make_engine, make_session_factory
from .logging_setup import configure_traffic_logging
from .models import (
    CreateBoardRequest,
    CreateCardRequest,
    CreateColumnRequest,
    MoveCardRequest,
    SimulateDbErrorRequest,
    UpdateCardRequest,
)
from .services import KanbanService
from .services.db_simulation import set_simulation
from .validation import validate_body
from .validator_gateways import KanbanValidatorGateway, SourceJson

_STATIC_DIR = Path(__file__).parent / "static"


def _source_json(request: Request) -> SourceJson:
    return SourceJson(url=request.url.path, method=request.method, caller_type="api_route")


def _error_response(exc: DomainError) -> JSONResponse:
    return to_json_response(build_error_response(exc))


def create_app(session_factory: SessionFactory | None = None) -> Starlette:
    """App factory. With no arguments, builds the real SQLite file and
    creates its schema on startup — the production path. Tests pass their
    own `session_factory` (already pointed at a fresh in-memory database
    with its schema already created), for full isolation between tests."""
    owns_engine = session_factory is None
    if session_factory is None:
        engine = make_engine(f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}")
        session_factory = make_session_factory(engine)

    service = KanbanService(session_factory)

    def get_gateway(request: Request) -> KanbanValidatorGateway:
        return KanbanValidatorGateway(service, source_json=_source_json(request))

    async def create_board(request: Request) -> JSONResponse:
        try:
            payload = await validate_body(request, CreateBoardRequest)
        except ValidationFailedError as exc:
            return _error_response(exc)
        gateway = get_gateway(request)
        result = await gateway.handle(gateway.controller.create_board, payload)
        return to_json_response(result)

    async def list_boards(request: Request) -> JSONResponse:
        gateway = get_gateway(request)
        result = await gateway.handle(gateway.controller.list_boards)
        return to_json_response(result)

    async def get_board(request: Request) -> JSONResponse:
        gateway = get_gateway(request)
        result = await gateway.handle(gateway.controller.get_board, request.path_params["board_id"])
        return to_json_response(result)

    async def delete_board(request: Request) -> JSONResponse:
        gateway = get_gateway(request)
        result = await gateway.handle(
            gateway.controller.delete_board, request.path_params["board_id"]
        )
        return to_json_response(result)

    async def add_column(request: Request) -> JSONResponse:
        try:
            payload = await validate_body(request, CreateColumnRequest)
        except ValidationFailedError as exc:
            return _error_response(exc)
        gateway = get_gateway(request)
        result = await gateway.handle(
            gateway.controller.add_column, request.path_params["board_id"], payload
        )
        return to_json_response(result)

    async def delete_column(request: Request) -> JSONResponse:
        gateway = get_gateway(request)
        result = await gateway.handle(
            gateway.controller.delete_column,
            request.path_params["board_id"],
            request.path_params["column_id"],
        )
        return to_json_response(result)

    async def create_card(request: Request) -> JSONResponse:
        try:
            payload = await validate_body(request, CreateCardRequest)
        except ValidationFailedError as exc:
            return _error_response(exc)
        gateway = get_gateway(request)
        result = await gateway.handle(
            gateway.controller.create_card, request.path_params["board_id"], payload
        )
        return to_json_response(result)

    async def update_card(request: Request) -> JSONResponse:
        try:
            payload = await validate_body(request, UpdateCardRequest)
        except ValidationFailedError as exc:
            return _error_response(exc)
        gateway = get_gateway(request)
        result = await gateway.handle(
            gateway.controller.update_card, request.path_params["card_id"], payload
        )
        return to_json_response(result)

    async def move_card(request: Request) -> JSONResponse:
        try:
            payload = await validate_body(request, MoveCardRequest)
        except ValidationFailedError as exc:
            return _error_response(exc)
        gateway = get_gateway(request)
        result = await gateway.handle(
            gateway.controller.move_card, request.path_params["card_id"], payload
        )
        return to_json_response(result)

    async def delete_card(request: Request) -> JSONResponse:
        gateway = get_gateway(request)
        result = await gateway.handle(
            gateway.controller.delete_card, request.path_params["card_id"]
        )
        return to_json_response(result)

    async def set_db_connection_simulation(request: Request) -> JSONResponse:
        """Test-only utility — deliberately NOT routed through a
        ValidatorGateway, unlike every route above. Flipping a flag isn't
        domain logic, so there's no controller for it; this exists purely
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
        set_simulation(mode)
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
