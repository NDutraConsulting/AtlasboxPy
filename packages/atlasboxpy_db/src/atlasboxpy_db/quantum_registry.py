"""DBQuantumRegistry owns every engine and session factory a
SQLAlchemy-backed caller hands out, cached by the resolved quantum's
name — so two calls that route to the same shard (whether from the same
ShardRouter or, incidentally, two different ones) share one connection
pool instead of each opening its own. This is the only thing that ever
calls create_async_engine.

A registry is meant to be constructed fresh per app/process instance,
not held as a module-level singleton — that's what gives a test suite
isolated engines with no special-casing: isolation is a consequence of
who constructs the registry and when, not something this module needs to
know about.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TypeAlias

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .db_quantum import DBDriver, DBQuantum
from .errors import StorageConflict, StorageTimeout, StorageUnavailable
from .shard_router import ShardRouter

# A zero-arg callable producing an AsyncSession — what an async_sessionmaker
# instance already is, without forcing every caller to depend on the
# concrete async_sessionmaker class specifically (a caller that wraps this
# — to re-check some "is the backend down right now?" flag on every call,
# say — just needs to produce the same shape back).
SessionOpener: TypeAlias = Callable[[], AsyncSession]

_EXPECTED_URL_PREFIX = {
    DBDriver.SQLITE: "sqlite",
    DBDriver.POSTGRESQL: "postgresql",
    DBDriver.MYSQL: "mysql",
}


class DBQuantumRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, AsyncEngine] = {}
        self._sessions: dict[str, SessionOpener] = {}

    def register_sessions(self, quantum_name: str, sessions: SessionOpener) -> None:
        """Pre-seed a quantum's session opener directly, bypassing URL
        resolution entirely — how a test hands this registry a fresh,
        already-built in-memory-database session factory instead of
        letting `sessions()` build one from the quantum's configured URL.
        Keyed by the resolved shard's own name, the same key `sessions()`
        below would have used — a caller that pre-seeds doesn't need to
        know a ShardRouter was ever involved."""
        self._sessions[quantum_name] = sessions

    def sessions(self, router: ShardRouter[DBQuantum], shard_key: str = "") -> SessionOpener:
        """The session opener for whichever shard `shard_key` routes to.
        A single-shard router (today's common case) needs no key at all
        — every key routes to that one shard, so the default `""` is
        exactly as correct as any other value would be. A real sharded
        router expects a real key (a tenant id, a board id, ...)."""
        quantum = router.shard_for(shard_key)
        cached = self._sessions.get(quantum.name)
        if cached is not None:
            return cached
        engine = self._engine_for(quantum)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        self._sessions[quantum.name] = factory
        return factory

    def _engine_for(self, quantum: DBQuantum) -> AsyncEngine:
        engine = self._engines.get(quantum.name)
        if engine is not None:
            return engine
        url = quantum.resolve_url()
        expected_prefix = _EXPECTED_URL_PREFIX[quantum.driver]
        if not url.startswith(expected_prefix):
            raise ValueError(
                f"DBQuantum(name={quantum.name!r}, driver={quantum.driver}) resolved a URL "
                f"that doesn't start with {expected_prefix!r}: {url!r}"
            )
        engine = create_async_engine(url)
        self._engines[quantum.name] = engine
        return engine


@asynccontextmanager
async def session_scope(sessions: SessionOpener) -> AsyncIterator[AsyncSession]:
    """Commits on a clean exit, rolls back on any exception, and
    translates SQLAlchemy-specific failures into this package's
    backend-neutral storage exceptions (errors.py) — the one place every
    caller funnels through, so no individual query method needs its own
    try/except for this."""
    async with sessions() as session:
        try:
            yield session
            await session.commit()
        except SATimeoutError as exc:
            await session.rollback()
            raise StorageTimeout(str(exc)) from exc
        except OperationalError as exc:
            await session.rollback()
            raise StorageUnavailable(str(exc)) from exc
        except IntegrityError as exc:
            await session.rollback()
            raise StorageConflict(str(exc)) from exc
        except Exception:
            await session.rollback()
            raise
