"""A debug-only knob services and repositories check when acquiring a
database session — not one calling another, but each reading the same
shared process state, the same way any of them might read an env var or a
feature flag. Lives at the top level (a sibling of db.py), not inside
services/, specifically so both services/ and repositories/ can depend on
it without depending on each other.

Simulates "the database connection is down" or "the database is slow" via
GENUINE SQLAlchemy/SQLite failures, not a hand-raised fake exception:

- "error" swaps in an engine pointed at a directory that can't exist, so
  aiosqlite's own connect() genuinely raises sqlalchemy.exc.OperationalError
  ("unable to open database file") the moment a real query is attempted.
- "timeout" swaps in an engine whose connection pool has exactly one slot,
  permanently checked out, so a real query genuinely raises
  sqlalchemy.exc.TimeoutError waiting for a connection that will never
  free up — a real pool exhaustion, not a manufactured asyncio.sleep().

Toggled via POST /api/debug/db-connection — see main.py. The resulting
real exceptions are translated into a ServiceResult by
services/results.py's `translate_db_errors` — kept there, not here, since
that translation is a services/-only concept and this module needs to
stay usable by repositories/ too, without either package depending on the
other.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from .db import SessionFactory, make_session_factory

SimulationMode = Literal["error", "timeout"] | None

_UNREACHABLE_DB_URL = "sqlite+aiosqlite:////nonexistent-directory-for-simulated-db-outage/kanban.db"

_mode: SimulationMode = None
_broken_engine: AsyncEngine | None = None
_held_connection: AsyncConnection | None = None


async def set_simulation(mode: SimulationMode) -> None:
    """Toggle the simulated failure. Tears down any previous broken engine
    (releasing the connection a "timeout" simulation was holding) before
    switching to the new mode."""
    global _mode, _broken_engine, _held_connection
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


def active_session_factory(real_factory: SessionFactory) -> SessionFactory:
    """The session factory a caller should use for this call: the real
    one, or — while a simulation is active — one backed by a genuinely
    broken engine (see module docstring)."""
    if _broken_engine is None:
        return real_factory
    return make_session_factory(_broken_engine)
