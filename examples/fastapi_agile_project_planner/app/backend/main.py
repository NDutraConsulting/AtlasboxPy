"""Kanban + agile-project-planning demo composition root: Starlette +
SQLite (via SQLAlchemy) backend, plus a static, DDD-organized frontend —
one folder per feature/page, each holding its own CSS and a
{feature}-controller.js that orchestrates {feature}-api.js + {feature}-ui.js.

Started as a copy of examples/fastapi_kanban and is where this
workspace's project-planning and AI-agent-adjacent features grow over
time — see docs/decisions.md's ADR-4 and
KanbanController.find_related_tasks_by_card for the first one:
KanbanController orchestrating three services (UserSessionService,
KanbanService, TaskAgentService), each owning one bounded concern.

Backend layering:

    routes (thin HTTP forwarding) > controllers (validate props,
        orchestrate services, decide what a failure means) > services
        (business rules) > infrastructure (repositories, database)

This file owns none of that — it's the composition root, and only the
composition root: it registers which database each entity repository's
storage layer should use (`DBQuantumRegistry`), constructs `KanbanController`,
wires `routes/kanban_routes.py`'s routes plus the static frontend mount
into one Starlette app, registers the atlasboxpy_telemetry trace-toggle
header middleware, and manages the app lifespan. No HTTP handler body, no
controller logic, and no SQLAlchemy import lives here.

Run it with:
    pip install -e "packages/atlasboxpy_controller[dev]"   # needs sqlalchemy + aiosqlite
    pip install -e "packages/atlasboxpy_repository"
    pip install -e "packages/atlasboxpy_db"
    pip install -e "packages/atlasboxpy_api"
    pip install -e "packages/atlasboxpy_service"
    pip install -e "packages/atlasboxpy_telemetry"
    uvicorn examples.fastapi_agile_project_planner.app.backend.main:app --reload
(or just ./run.sh from examples/fastapi_agile_project_planner/)

Then open http://127.0.0.1:8000/ in a browser. Every request that moves
through the controller is logged to
examples/fastapi_agile_project_planner/app/.logs/{YYYY-mm-dd}_atlasboxpy_controller.log
— see logging_setup.py. A request carrying "X-Trace-Debug: true" also
gets its full call-chain spans logged to
{YYYY-mm-dd}_atlasboxpy_telemetry.log in that same directory, regardless
of the process-wide ATLASBOXPY_TELEMETRY_ENABLED default.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from atlasboxpy_api import HeaderContextMiddleware
from atlasboxpy_db import DBQuantumRegistry, VariantRouter
from atlasboxpy_telemetry import trace_override
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from .controllers import KanbanController
from .infrastructure.database.db_connections.kanban_db_quantum import KANBAN_DB_QUANTUM
from .infrastructure.database.session import (
    DEFAULT_DB_PATH,
    SessionFactory,
    init_db,
    make_engine,
    make_session_factory,
    set_default_quantum_registry,
)
from .logging_setup import configure_telemetry_logging, configure_traffic_logging
from .routes.kanban_routes import build_routes

_STATIC_DIR = Path(__file__).parent.parent / "frontend" / "static"

# A request carrying "X-Trace-Debug: true" gets every atlasboxpy_telemetry
# span in its call chain logged, regardless of the process-wide
# ATLASBOXPY_TELEMETRY_ENABLED default — enabling tracing for one
# specific request in a deployed environment, with no config change and
# no redeploy. Any other header value (or no header at all) falls back
# to that process default; VariantRouter's exact-match-or-default
# semantics mean a malformed header can never turn tracing on by
# accident (see atlasboxpy_db's own ADR-4).
_TRACE_DEBUG_HEADER: VariantRouter[bool | None] = VariantRouter(
    name="trace-debug", default=None, variants={"true": True}
)


def create_app(session_factory: SessionFactory | None = None) -> Starlette:
    """App factory. With no arguments, builds the real SQLite file and
    creates its schema on startup — the production path. Tests pass their
    own `session_factory` (already pointed at a fresh in-memory database
    with its schema already created), for full isolation between tests."""
    owns_engine = session_factory is None
    if session_factory is None:
        # aiosqlite/sqlite3 won't create a missing parent directory — only
        # the file inside it — so a fresh clone (this directory is
        # gitignored, nothing to check out) needs it created explicitly,
        # the same way logging_setup.py creates its own log directory.
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        engine = make_engine(f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}")
        session_factory = make_session_factory(engine)

    # The one place this app registers which database its entity storages
    # should use — the composition root's job, not a controller's or
    # repository's. See infrastructure/database/session.py's module docstring.
    registry = DBQuantumRegistry()
    registry.register_sessions(KANBAN_DB_QUANTUM.name, session_factory)
    set_default_quantum_registry(registry)
    controller = KanbanController()

    routes = [
        *build_routes(controller),
        # Registered after the API routes so /api/* is matched first — the
        # static mount at "/" would otherwise greedily swallow every path.
        Mount("/", app=StaticFiles(directory=str(_STATIC_DIR), html=True), name="static"),
    ]

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        if owns_engine:
            await init_db(engine)
        yield

    middleware = [
        Middleware(
            HeaderContextMiddleware[bool | None],
            header_name="X-Trace-Debug",
            context=trace_override,
            resolve=_TRACE_DEBUG_HEADER.resolve,
        ),
    ]

    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


configure_traffic_logging()
configure_telemetry_logging()
app = create_app()
