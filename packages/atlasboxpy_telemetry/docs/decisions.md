# Architecture decisions

Lightweight ADRs for the choices in this package that a developer
evaluating or extending it would reasonably ask "why not the obvious
alternative?" about. Each one names what was actually considered and
rejected, not a strawman.

## Which decision applies to what you're doing

```
Extending or reasoning about atlasboxpy_telemetry?
│
├─ Wondering why this package depends on atlasboxpy_api, when every
│  other atlasboxpy_* package here is an independent sibling?
│    └─→ ADR-1: this is the one genuine exception — trace/span
│         propagation IS the same "state scoped to one request,
│         invisible to concurrent ones" problem atlasboxpy_api's
│         RequestContext already solved. Re-implementing ContextVar
│         wrapping a third time here would be the exact kind of
│         restated-in-a-second-file cruft this ecosystem has
│         consistently avoided elsewhere.
│
└─ Expecting spans to show up in Jaeger/an OTel collector/Datadog
   automatically?
     └─→ ADR-2: they don't — spans are logged, not exported. See that
          ADR for why a log line is the deliberate v1 default, not a
          missing feature.
```

---

## ADR-1: Depends on `atlasboxpy_api` for `RequestContext` — the first cross-package dependency in this ecosystem

**Context.** Every `atlasboxpy_*` package built before this one
(`atlasboxpy_controller`, `atlasboxpy_repository`, `atlasboxpy_db`,
`atlasboxpy_service`, `atlasboxpy_api` itself) is a deliberate,
independent sibling with zero required dependency on another package in
this workspace — a real, consistent architectural stance, not an
accident. This package needs exactly the mechanism `atlasboxpy_api`
already built for the shadow-DB-routing use case: a value scoped to one
in-flight request, correctly isolated between concurrent requests on the
same event loop, propagated through whatever that request's task
`await`s.

**Decision.** `atlasboxpy_telemetry` takes `atlasboxpy_api` as a real
dependency (`pyproject.toml`'s `dependencies`) and uses its
`RequestContext` directly for `trace_id`, the current-span tracker, and
the per-request enable/disable override — no separate `ContextVar`
wrapper is written here.

**Alternatives considered**
- Re-implement a local `ContextVar` wrapper inside this package instead
  of depending on `atlasboxpy_api` — keeps the "every package is an
  independent sibling" pattern unbroken, at the cost of restating
  `RequestContext`'s exact ~15 lines a second time, in a second package,
  for the identical problem — precisely the kind of "second file
  restating the first file's job" this ecosystem's own `examples/fastapi_kanban`
  ADR-1 explicitly rejected doing for storage interfaces. A bug fix or
  behavior change to request-scoped context propagation would then need
  to happen in two places, kept in sync by hand.
- Depend on `atlasboxpy_controller` instead, and add `RequestContext`
  there — rejected: `BaseController`'s job is response formatting, not
  request-scoped context; conflating the two would mean adopting
  telemetry requires adopting the controller package's whole
  response-envelope opinion too, whether or not an app wants that.
- Chosen: depend on `atlasboxpy_api` specifically, since request-scoped
  context propagation is *exactly* what it already is, with no framework
  or response-shape baggage attached.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | — | — |
| Portability | Any bug fix or improvement to `RequestContext`'s propagation semantics benefits this package automatically, with no duplicated code to keep in sync. | Installing `atlasboxpy_telemetry` now always installs `atlasboxpy_api` too — a real (if small) dependency-graph cost that every previous package in this ecosystem specifically avoided. |
| Debuggability | One canonical implementation of "how does request-scoped context work here" — a developer who understands `atlasboxpy_api`'s `RequestContext` already understands how `trace_id`/span tracking behaves, with nothing telemetry-specific to relearn. | — |
| Evolvability | If `atlasboxpy_api` ever adds something like distributed (cross-process) propagation, this package inherits that capability without a rewrite. | This package's own evolution is now coupled to `atlasboxpy_api`'s — a breaking change there (unlikely, given how small its surface is, but possible) has to be accounted for here too. |

---

## ADR-2: Spans are logged, not exported to a tracing backend

**Context.** "Real" distributed tracing usually means spans exported to
a backend (Jaeger, an OTel collector, Datadog, ...) that can render a
full waterfall view of a request's call chain. Building that export path
means picking a wire protocol, a backend to target, and handling that
backend being unavailable — real scope, and an external dependency this
prototype workspace has consistently avoided taking on for its own sake
(see `atlasboxpy_repository`'s Redis backend, imported lazily and never
required).

**Decision.** A completed span is logged as one structured line through
the standard `logging` module (`logging.getLogger("atlasboxpy_telemetry")`)
— trace id, span id, parent span id, name, outcome, duration, and
attributes, all in one line. Nothing here talks to a tracing backend.

**Alternatives considered**
- A real OTel SDK integration (spans exported via OTLP to a collector)
  — the "correct" production answer for a team that already runs tracing
  infrastructure, but it's a genuinely different scope: a new required
  dependency, a backend to configure and run, and failure modes (the
  collector is down, network is slow) this package would then need to
  handle gracefully so tracing itself never becomes a source of request
  latency or failures.
- No structured format at all — a plain `logger.info("span started")`/
  `("span ended")` pair — would work for a human skimming logs live, but
  loses the one property that makes a log line actually *tracing* rather
  than generic logging: a shared trace id and parent/child span ids a
  later process (a log aggregator, a script, a human with `grep`) can
  use to reconstruct the whole call tree for one request.
- Chosen: structured log lines, no export path. Every field a real
  tracing backend would want (trace id, span id, parent id, timing) is
  already present in each line — pointing a log shipper at this logger's
  output and feeding it into something that understands trace/span ids
  is a deployment-time decision, not a code change here.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | No network call per span, no batching/buffering to get right — a log write is the only cost, and it's skipped entirely when telemetry is disabled (`is_enabled()` gates the write, not the bookkeeping). | A log line is generated (when enabled) even for a span with sub-millisecond duration — no built-in sampling; a very hot path with tracing left on would log a line per call. |
| Portability | Works anywhere `logging` works — no backend to stand up to get value from this package immediately, including in a local dev environment or a demo app with no observability infrastructure at all. | Cross-process (genuinely distributed) tracing isn't covered — an outbound call to a real separate service doesn't automatically carry the trace id across that boundary; that's explicitly out of scope for this version (see README). |
| Debuggability | `grep`-ing logs for one `trace_id` reconstructs a full call tree immediately, with no separate tool or UI needed — real value with zero setup. | Without an actual trace-visualization backend, reconstructing a *wide* or deeply nested call tree from log lines by hand is more tedious than a waterfall UI would be — this trades setup cost for reconstruction effort. |
| Evolvability | A real exporter can be added later as an *additional* sink (a second handler on the same logger, or a new method) without changing how `Tracer.span(...)` is used at any call site — every existing `async with tracer.span(...)` call keeps working unchanged. | — |
