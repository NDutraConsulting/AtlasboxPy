"""A debug-only knob orm_models/ checks when acquiring a database session
— read as shared process state (the same way any module might read an
env var or a feature flag), not threaded in as a parameter. Lives in
db_connections/, this app's own layer for wrapping atlasboxpy_db's
generic session-opener contract with kanban-specific behavior, so any
orm_model can depend on it without depending on services/ or
repositories/.

Simulates "the database connection is down" or "the database is slow" via
GENUINE SQLAlchemy/SQLite failures, not a hand-raised fake exception:

- "error" swaps in an engine pointed at a directory that can't exist, so
  aiosqlite's own connect() genuinely raises sqlalchemy.exc.OperationalError
  ("unable to open database file") the moment a real query is attempted.
- "timeout" swaps in an engine whose connection pool has exactly one slot,
  permanently checked out, so a real query genuinely raises
  sqlalchemy.exc.TimeoutError waiting for a connection that will never
  free up — a real pool exhaustion, not a manufactured asyncio.sleep().

Toggled via POST /api/debug/db-connection — see routes/kanban_routes.py.
The resulting real exceptions are translated into backend-neutral ones
by atlasboxpy_db's `session_scope`, then into a ServiceResult by
services/results.py's `translate_db_errors`.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from atlasboxpy_db import SessionOpener
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from ..session import make_session_factory

SimulationMode = Literal["error", "timeout"] | None

_UNREACHABLE_DB_URL = "sqlite+aiosqlite:////nonexistent-directory-for-simulated-db-outage/kanban.db"

_mode: SimulationMode = None
_broken_engine: AsyncEngine | None = None
_held_connection: AsyncConnection | None = None
# Guards the whole teardown-then-setup sequence in set_simulation() below,
# which awaits multiple times (closing a held connection, disposing an
# engine, opening a new one) while reading and writing the three globals
# above. Without it, two concurrent toggle calls (POST
# /api/debug/db-connection twice in a row before the first finishes) can
# interleave: one call's teardown sees the other's not-yet-assigned state
# and no-ops, then overwrites it with its own — leaving the simulation
# stuck in an unintended mode and leaking a permanently-checked-out
# connection nothing then disposes.
_lock = asyncio.Lock()


async def set_simulation(mode: SimulationMode) -> None:
    """Toggle the simulated failure. Tears down any previous broken engine
    (releasing the connection a "timeout" simulation was holding) before
    switching to the new mode."""
    global _mode, _broken_engine, _held_connection
    async with _lock:
        if _held_connection is not None:
            await _held_connection.close()
            _held_connection = None
        if _broken_engine is not None:
            await _broken_engine.dispose()
            _broken_engine = None

        _mode = mode
        if mode == "timeout":
            _broken_engine = create_async_engine(
                "sqlite+aiosqlite:///:memory:",
                poolclass=AsyncAdaptedQueuePool,
                pool_size=1,
                max_overflow=0,
                pool_timeout=0.05,
            )
            # Permanently checks out the pool's only connection, so any real
            # query issued while this simulation is active genuinely times out
            # waiting for a connection slot that will never free up.
            _held_connection = await _broken_engine.connect()
        elif mode == "error":
            _broken_engine = create_async_engine(_UNREACHABLE_DB_URL)


def get_simulation() -> SimulationMode:
    return _mode


def active_session_factory(real_factory: SessionOpener) -> SessionOpener:
    """The session factory a caller should use for this call: the real
    one, or — while a simulation is active — one backed by a genuinely
    broken engine (see module docstring)."""
    if _broken_engine is None:
        return real_factory
    return make_session_factory(_broken_engine)
