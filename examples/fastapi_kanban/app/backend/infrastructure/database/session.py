"""SQLAlchemy async engine/session setup.

`make_session_factory(url)` is a plain factory — main.py calls it once with
the real SQLite file; tests call it with an in-memory database, fresh per
test, for full isolation.

`set_default_quantum_registry`/`get_default_quantum_registry` are the one
piece of shared process state here — the same kind of thing
db_connections/db_simulation.py's `set_simulation`/`get_simulation`
already are: read at the point of use (kanban_storages.py's composition
helper), not threaded as an explicit parameter through every layer
between the app entry point and the orm_model that actually needs it.
That's what keeps a `DBQuantumRegistry` — a persistence-layer type — out
of KanbanService's and KanbanController's constructors entirely; only
main.py (the composition root) and kanban_storages.py ever reference it.
main.py still calls `set_default_quantum_registry` once per
`create_app()` — including once per test, via the `client` fixture — so
test isolation is unchanged: each test still gets its own fresh in-memory
engine, just registered instead of passed down by hand.
"""

from __future__ import annotations

from pathlib import Path

from atlasboxpy_db import DBQuantumRegistry
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .tables import Base

DEFAULT_DB_PATH = Path(__file__).parent / "sqlite" / "kanban.db"

SessionFactory = async_sessionmaker[AsyncSession]

_default_quantum_registry: DBQuantumRegistry | None = None


def make_engine(url: str, **engine_kwargs: object) -> AsyncEngine:
    return create_async_engine(url, echo=False, **engine_kwargs)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


def set_default_quantum_registry(registry: DBQuantumRegistry) -> None:
    """Called once by main.py's create_app() — the app's own registry, or
    a test's fresh one pre-seeded with an in-memory database — before any
    orm_model is constructed."""
    global _default_quantum_registry
    _default_quantum_registry = registry


def get_default_quantum_registry() -> DBQuantumRegistry:
    if _default_quantum_registry is None:
        raise RuntimeError(
            "No default DBQuantumRegistry configured — call set_default_quantum_registry() "
            "(main.py's create_app() does this) before constructing a storage."
        )
    return _default_quantum_registry
