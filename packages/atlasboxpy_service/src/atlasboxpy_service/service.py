"""BaseService — the same auto-wrapping mechanism as atlasboxpy_controller's
BaseController (`__init_subclass__` wraps every public async method
defined directly on a subclass, at class-definition time), aimed at a
different job: every wrapped method is logged both when it's called and
when it completes — success or failure — not just on failure the way a
controller's wrap does.

A service's own methods in this ecosystem don't raise for expected
outcomes — "validation failed" or "not found" is data a service returns
(see this package's README for the service-responsibility convention
this follows), not something it raises. An exception reaching this
wrapper is therefore a genuine bug, not an expected-outcome path: it's
logged at ERROR with the traceback and re-raised, never swallowed or
translated into some other shape. That translation (an exception into a
DomainError, into an HTTP status) is atlasboxpy_controller's job, one
layer up — BaseService has no opinion about it and no dependency on that
package.

Leading-underscore methods are left untouched, same convention as
atlasboxpy_controller's ExceptionFormatter — they're internal helpers,
not entrypoints worth logging as if they were.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

_MAX_REPR_LENGTH = 200


def _short_repr(value: Any) -> str:
    """Truncates a call's args/result before logging — a service can be
    handed or return a large object (a full Card list, say), and a log
    line isn't the place for its full contents."""
    text = repr(value)
    if len(text) > _MAX_REPR_LENGTH:
        return text[: _MAX_REPR_LENGTH - 1] + "…"
    return text


def _wrap(
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, Any]]:
    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        logger: logging.Logger = self.logger
        name = func.__name__
        logger.info(
            "service_call method=%s args=%s kwargs=%s",
            name, _short_repr(args), _short_repr(kwargs),
        )
        start = time.monotonic()
        try:
            result = await func(self, *args, **kwargs)
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "service_call method=%s status=error duration_ms=%.1f",
                name, duration_ms, exc_info=exc,
            )
            raise
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "service_call method=%s status=ok duration_ms=%.1f result=%s",
            name, duration_ms, _short_repr(result),
        )
        return result

    return wrapper


class BaseService:
    """Subclass this and call `super().__init__()` — every public async
    method defined directly on the subclass gets wrapped at
    class-definition time to log its call and its outcome (success or
    failure) through `self.logger`. See the module docstring for what
    happens on an unexpected exception, and `gather_named` below for the
    concurrent-call helper every wrapped method can use."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(self.__class__.__module__)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, attr in list(vars(cls).items()):
            if not name.startswith("_") and inspect.iscoroutinefunction(attr):
                setattr(cls, name, _wrap(attr))

    async def gather_named(self, **calls: Awaitable[Any]) -> dict[str, Any]:
        """Runs every keyword-given awaitable concurrently, logging each
        one's start/success/failure individually through `self.logger`
        by its keyword name, and returns `{name: result}`. Propagates
        the first exception raised (the same semantics as
        `asyncio.gather`'s default, `return_exceptions=False`) — an
        orchestrated operation where one leg fails is a failure of the
        whole operation, not a partial result to silently paper over.

        Generalizes the `asyncio.gather(...)` pattern this ecosystem's
        own example app hand-wrote per call site before this helper
        existed — see this package's README for a worked before/after.
        """
        names = list(calls.keys())

        async def _run(name: str, awaitable: Awaitable[Any]) -> Any:
            self.logger.info("service_call_concurrent name=%s status=start", name)
            try:
                result = await awaitable
            except Exception as exc:
                self.logger.error(
                    "service_call_concurrent name=%s status=error", name, exc_info=exc
                )
                raise
            self.logger.info(
                "service_call_concurrent name=%s status=ok result=%s",
                name, _short_repr(result),
            )
            return result

        results = await asyncio.gather(*(_run(name, calls[name]) for name in names))
        return dict(zip(names, results, strict=True))
