"""SQLAlchemy async engine/session setup.

`make_session_factory(url)` is a plain factory — main.py calls it once with
the real SQLite file; tests call it with an in-memory database, fresh per
test, for full isolation.

`set_default_session_factory`/`get_default_session_factory` are the one
piece of shared process state here — the same kind of thing
db_simulation.py's `set_simulation`/`get_simulation` already are: read at
the point of use (KanbanRepository's constructor), not threaded as an
explicit parameter through every layer between the app entry point and
the repository that actually needs it. That's what keeps `SessionFactory`
— a persistence-layer type — out of KanbanService's and KanbanController's
constructors entirely; only main.py (the composition root) and
KanbanRepository ever reference it. main.py still calls
`set_default_session_factory` once per `create_app()` — including once per
test, via the `client` fixture — so test isolation is unchanged: each test
still gets its own fresh in-memory engine, just registered instead of
passed down by hand.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .orm_models import Base

DEFAULT_DB_PATH = Path(__file__).parent / "kanban.db"

SessionFactory = async_sessionmaker[AsyncSession]

_default_session_factory: SessionFactory | None = None


def make_engine(url: str, **engine_kwargs: object) -> AsyncEngine:
    return create_async_engine(url, echo=False, **engine_kwargs)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


def set_default_session_factory(factory: SessionFactory) -> None:
    """Called once by main.py's create_app() — the app's own DB, or a
    test's fresh in-memory one — before any repository is constructed."""
    global _default_session_factory
    _default_session_factory = factory


def get_default_session_factory() -> SessionFactory:
    if _default_session_factory is None:
        raise RuntimeError(
            "No default session factory configured — call set_default_session_factory() "
            "(main.py's create_app() does this) before constructing a repository."
        )
    return _default_session_factory


@asynccontextmanager
async def session_scope(factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    """Commits on a clean exit, rolls back on any exception — services use
    this instead of managing transactions by hand at every call site."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
