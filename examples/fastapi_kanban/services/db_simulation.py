"""A debug-only knob both services check independently — this is NOT a
service calling a service, it's each service reading a shared piece of
process state, the same way both might read an env var or a feature flag.
Lets you simulate "the database connection is down" (immediate failure)
or "the database is slow" (a timeout) to exercise those paths on demand.

Toggled via POST /api/debug/db-connection — see main.py.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Literal, ParamSpec, TypeVar

from .results import ServiceResult

SimulationMode = Literal["error", "timeout"] | None

P = ParamSpec("P")

_mode: SimulationMode = None


def set_simulation(mode: SimulationMode) -> None:
    global _mode
    _mode = mode


def get_simulation() -> SimulationMode:
    return _mode


class SimulatedDbError(Exception):
    pass


class SimulatedDbTimeout(Exception):
    pass


async def check_simulation() -> None:
    """Call at the top of every service method that touches the database."""
    mode = get_simulation()
    if mode == "error":
        raise SimulatedDbError("Database connection failed (simulated)")
    if mode == "timeout":
        await asyncio.sleep(0.05)
        raise SimulatedDbTimeout("Database call timed out (simulated)")


def translate_db_errors(
    fn: Callable[P, Awaitable[ServiceResult]],
) -> Callable[P, Awaitable[ServiceResult]]:
    """Wraps a service method so a simulated (or real, for SimulatedDbError's
    real-world counterparts) DB failure always comes back as a ServiceResult
    instead of an uncaught exception — every method still calls
    `await check_simulation()` itself, this just centralizes translating
    what it raises into the envelope."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> ServiceResult:
        try:
            return await fn(*args, **kwargs)
        except SimulatedDbTimeout as exc:
            return ServiceResult.timeout(str(exc))
        except SimulatedDbError as exc:
            return ServiceResult.error(str(exc), code="upstream_error")

    return wrapper
