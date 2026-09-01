"""Tracer — real trace propagation: one trace id shared across every
span in a request's call chain, spans recording parent/child
relationships automatically via context (the same `ContextVar`-stacking
`atlasboxpy_api`'s `HeaderContextMiddleware` already relies on), each
span logged as one structured line — no external tracing backend
required. See this package's own ADR-1 for why a log line, not a real
exporter, is the deliberate default; nothing here prevents pointing a
log shipper at these lines later.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from atlasboxpy_api import RequestContext

from .config import is_enabled

# None = no trace established yet for this task tree — the first span
# entered generates one; every nested span reuses it via context.
trace_id: RequestContext[str | None] = RequestContext("atlasboxpy-telemetry-trace-id", default=None)
_current_span_id: RequestContext[str | None] = RequestContext(
    "atlasboxpy-telemetry-span-id", default=None
)


@dataclass(frozen=True)
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)


def get_current_trace_id() -> str | None:
    return trace_id.get()


def get_current_span_id() -> str | None:
    return _current_span_id.get()


class Tracer:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("atlasboxpy_telemetry")

    @asynccontextmanager
    async def span(self, span_name: str, /, **attributes: Any) -> AsyncIterator[Span]:
        """Opens a span for the duration of the `async with` block. The
        first span entered in a request establishes `trace_id` (a fresh
        one, unless something upstream already set it); every span
        nested inside it — including ones opened by a different
        `Tracer` instance, or a different service several calls deeper —
        shares that same trace id and correctly records its immediate
        caller as `parent_span_id`, purely from context, with no
        explicit parent threaded through by hand.

        `span_name` is positional-only (note the `/`) specifically so it
        can never collide with an attribute a caller passes — `name` is
        one of the most common field names in any codebase, and
        `async with tracer.span("add_column", name=column_name)` would
        otherwise raise `TypeError: got multiple values for argument
        'name'` the moment a caller's own attribute happened to share
        this parameter's name.
        """
        current_trace_id = trace_id.get() or str(uuid.uuid4())
        parent_span_id = _current_span_id.get()
        span_id = str(uuid.uuid4())
        current_span = Span(
            trace_id=current_trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=span_name,
            attributes=dict(attributes),
        )

        trace_token = trace_id.set(current_trace_id)
        span_token = _current_span_id.set(span_id)
        start = time.monotonic()
        outcome = "ok"
        try:
            yield current_span
        except Exception:
            outcome = "error"
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            if is_enabled():
                self.logger.info(
                    "trace_id=%s span_id=%s parent_span_id=%s name=%s "
                    "outcome=%s duration_ms=%.1f attributes=%s",
                    current_span.trace_id,
                    current_span.span_id,
                    current_span.parent_span_id,
                    current_span.name,
                    outcome,
                    duration_ms,
                    current_span.attributes,
                )
            _current_span_id.reset(span_token)
            trace_id.reset(trace_token)
