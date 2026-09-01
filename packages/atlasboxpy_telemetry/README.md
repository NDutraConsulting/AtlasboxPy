# atlasboxpy-telemetry

`Tracer`: real (not toy) trace propagation — one trace id shared across
a request's whole call chain, spans recording parent/child relationships
automatically via context, each span logged as one structured line. No
external tracing backend required to get real value out of this; nothing
here prevents pointing a log shipper at these lines later. Built on
`atlasboxpy_api`'s `RequestContext` rather than re-implementing the same
`ContextVar` propagation a third time.

Toggleable two ways: a process-wide default from one environment
variable, and a per-request override carried by a REST header (via
`atlasboxpy_api`'s `HeaderContextMiddleware`) — the case this package
was built for: enabling a fully traced call chain for one specific
post-prod request, with no config change and no deploy.

## Install

> **This is a prototype/example project — it is not published to PyPI and there's no plan to.** The `pip install` commands below are illustrative only; install from a local clone with `pip install -e .` to actually use it.

```bash
pip install atlasboxpy-telemetry
```

## Usage

```python
from atlasboxpy_telemetry import Tracer

tracer = Tracer()

class KanbanService(BaseService):
    async def get_board(self, board_id: str) -> ServiceResult:
        async with tracer.span("get_board", board_id=board_id):
            board, columns, cards = await self.gather_named(
                board=self._boards.get_by_id(board_id),
                columns=self._columns.list_for_board(board_id),
                cards=self._cards.list_for_board(board_id),
            )
            ...
```

Every call inside the `async with` block — including `gather_named`'s
own concurrent calls, and any nested `tracer.span(...)` a repository or
another service opens further down — is automatically attributed to the
same trace id and gets the right `parent_span_id`, purely from context.
No trace id or span id is ever threaded through a function signature by
hand.

### Toggling it on

Process-wide, for a whole deployment:

```bash
export ATLASBOXPY_TELEMETRY_ENABLED=true
```

Per-request, without touching config or redeploying — wire the override
context to a header at your composition root:

```python
from atlasboxpy_api import HeaderContextMiddleware
from atlasboxpy_db import VariantRouter
from atlasboxpy_telemetry import trace_override

TRACE_TOGGLE = VariantRouter(name="trace-debug", default=False, variants={"true": True})

app.add_middleware(
    HeaderContextMiddleware,
    header_name="X-Trace-Debug",
    context=trace_override,
    resolve=TRACE_TOGGLE.resolve,
)
```

A request carrying `X-Trace-Debug: true` now gets every span in its call
chain logged, regardless of the process-wide default; every other
request is unaffected.

## What this package does and doesn't do

- **Does:** generate a trace id and per-span ids, track parent/child
  span relationships via context (not by threading ids through function
  signatures), and log each completed span as one structured line —
  only when telemetry is enabled for that request.
- **Does:** resolve "enabled" as a per-request override (if one was set)
  falling back to a process-wide env-var default — never anything more
  elaborate than that for v1.
- **Doesn't:** export spans to an external tracing backend (Jaeger, an
  OTel collector, Datadog) — spans are logged, not shipped anywhere by
  this package. Pointing a log shipper at `atlasboxpy_telemetry`'s
  logger output is a deployment concern, not something this package
  does for you.
- **Doesn't:** propagate a trace id across a real network boundary (an
  outbound HTTP/LLM call to another service). Everything this package
  currently threads together happens in-process, via `ContextVar`; a
  genuinely distributed trace (crossing into a separate process) would
  need the trace id serialized into an outbound request header — not
  built here yet.

## Documentation

- [`docs/decisions.md`](docs/decisions.md) — ADRs for the non-obvious
  choices (logging instead of exporting to an external backend, why this
  package depends on `atlasboxpy_api` — the first cross-package
  dependency in this ecosystem — instead of re-implementing its own
  context propagation), each with alternatives considered and
  performance/portability/debuggability/evolvability trade-offs.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
