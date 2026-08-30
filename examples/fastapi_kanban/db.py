"""SQLAlchemy async engine/session setup.

`make_session_factory(url)` is a plain factory — main.py calls it once with
the real SQLite file; tests call it with an in-memory database, fresh per
test, for full isolation. Nothing here is a singleton import-time global,
so there's exactly one way to get a session factory, used consistently by
both the app and the test suite.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .orm_models import Base

DEFAULT_DB_PATH = Path(__file__).parent / "kanban.db"

SessionFactory = async_sessionmaker[AsyncSession]


def make_engine(url: str, **engine_kwargs: object) -> AsyncEngine:
    return create_async_engine(url, echo=False, **engine_kwargs)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


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
