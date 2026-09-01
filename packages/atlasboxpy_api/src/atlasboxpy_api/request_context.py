"""RequestContext — a thin, typed wrapper around `contextvars.ContextVar`
for state that must be scoped to exactly one in-flight request and never
leak into a concurrent one.

Why not a module-level global? A global is process-wide: under real
concurrency (multiple in-flight requests sharing one event loop), one
request's value can be overwritten by, or accidentally read by, a
different concurrent request — a real bug class, not a hypothetical one
(see the fastapi_kanban example's `db_simulation.py`, which needed an
explicit lock specifically because it uses a global for its own debug
toggle). `ContextVar` is asyncio's own mechanism for exactly this: each
task gets its own view, correctly propagated to whatever that task
`await`s, and invisible to any sibling task — no lock needed, because
there's nothing shared to race over.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Generic, TypeVar

T = TypeVar("T")


class RequestContext(Generic[T]):
    def __init__(self, name: str, default: T) -> None:
        self._var: ContextVar[T] = ContextVar(name, default=default)

    def get(self) -> T:
        return self._var.get()

    def set(self, value: T) -> Token[T]:
        return self._var.set(value)

    def reset(self, token: Token[T]) -> None:
        self._var.reset(token)
