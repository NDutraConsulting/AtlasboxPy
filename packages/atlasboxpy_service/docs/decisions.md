# Architecture decisions

Lightweight ADRs for the choices in this package that a developer
evaluating or extending it would reasonably ask "why not the obvious
alternative?" about. Each one names what was actually considered and
rejected, not a strawman.

## Which decision applies to what you're doing

```
Extending or reasoning about BaseService?
│
├─ Wondering why a successful call gets logged at all, when
│  BaseController only logs failures?
│    └─→ ADR-1: a controller's caller (an HTTP client, an agent) already
│         gets the outcome in its response — logging success there would
│         be pure duplication. A service's caller is other code, not a
│         human/agent watching a response; the log is often the only
│         record a successful service call happened at all.
│
├─ An unexpected exception reaches a wrapped service method — expecting
│  it to come back as some kind of error object, the way BaseController
│  returns an ErrorResponse?
│    └─→ ADR-2: it doesn't — BaseService logs it and re-raises. Services
│         in this ecosystem return their own expected-outcome type
│         (a ServiceResult, or whatever a given app defines) for
│         anything expected; an exception reaching this wrapper is
│         always a bug, and translating bugs into responses is
│         atlasboxpy_controller's job, one layer up.
│
└─ Calling gather_named with several concurrent calls, and one of them
   fails — expecting the others' results back anyway?
     └─→ ADR-3: no — gather_named propagates the first exception, same
          as asyncio.gather's default. A partial result from an
          orchestrated operation is exactly the kind of silent
          half-success this ecosystem avoids elsewhere (see
          examples/fastapi_kanban's own ADR-1 on cross-table atomicity).
```

---

## ADR-1: Every wrapped method logs both success and failure, not just failure

**Context.** `atlasboxpy_controller`'s `BaseController` only logs on
failure — a controller's caller (an HTTP client, an agent reading the
response directly) already receives the outcome in its response, so
logging a success there would just restate what the response already
says. A service's caller is different: it's other code, one or more
layers away from anything that produces a human- or agent-visible
response. Nothing else necessarily records that a given service call
happened, with what arguments, or how long it took.

**Decision.** `BaseService`'s wrap logs on both call and completion:
entry (method name + args), and outcome (success with a truncated
result, or failure with the exception and its traceback) — always,
regardless of what the method itself does.

**Alternatives considered**
- Mirror `BaseController` exactly (failure-only) — the more consistent
  choice across the two packages, but it means a service call's only
  observable trace, absent an explicit log statement the service author
  remembered to write, is *nothing* on the success path — no evidence
  it happened, no timing, no argument context if something downstream
  later needs to reconstruct what ran.
- Log only entry, not outcome — half the value: knowing a call started
  without knowing whether or how long it took to finish doesn't answer
  "did this actually work."
- Chosen: both, on every call — this package's whole reason to exist is
  the visibility gap `BaseController`'s failure-only logging
  deliberately leaves at the controller layer, filled in one layer down.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | One extra `logger.info` call per method invocation (both directions) — real but small next to the actual work a service method does (a DB round trip, a third-party API call). | A high-throughput service logging every call at INFO can produce meaningfully more log volume than `BaseController`'s failure-only approach — a caller who wants less can raise the log level or pass a filtered logger, but the default is verbose by design. |
| Portability | Works identically regardless of what a service's methods return — `_short_repr` truncates and logs anything, no coupling to a specific result type. | — |
| Debuggability | "Did this service method run, with what arguments, and how long did it take" is answerable from logs alone, without adding a print statement or a debugger — the entire point. | A log line's `result=` is a truncated `repr()`, not the full value — enough to recognize the outcome, not enough to reconstruct a large object from logs alone (deliberately: see `_short_repr`'s own docstring). |
| Evolvability | A new service method needs no logging code of its own — the wrap covers it the moment it's defined as a public async method. | — |

---

## ADR-2: An unexpected exception is logged and re-raised, never translated

**Context.** `BaseController`'s wrap catches everything and returns a
formatted `ErrorResponse` — a controller is the boundary where "what
does this failure mean to the caller" has to be answered, one way or
another, because there's nothing above it to answer that question.
`BaseService` sits below that boundary.

**Decision.** On an exception, `BaseService`'s wrap logs it (at ERROR,
with the traceback) and re-raises the exact same exception — no
wrapping, no translation, no swallowing.

**Alternatives considered**
- Translate into some kind of internal `ServiceError`/result type at the
  `BaseService` level — would require `BaseService` to define (and every
  consuming app to adopt) its own error-result shape, duplicating
  whatever shape a given app's services already use for *expected*
  outcomes (a `ServiceResult`, in `examples/fastapi_kanban`'s case) —
  now there'd be two different "something went wrong" shapes to
  reconcile at the controller boundary instead of one.
- Swallow the exception and return `None`/log-only — actively dangerous:
  a genuine bug (a real exception, not an expected outcome a service
  method already handles by returning its own result type) would
  silently disappear instead of surfacing anywhere.
- Chosen: log for visibility, re-raise unchanged — `BaseService` adds an
  observability hook, not a new control-flow layer. Whatever catches the
  exception above it (a controller's own wrap, in this ecosystem)
  decides what it means to a caller; `BaseService` has no opinion.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | — | — |
| Portability | `BaseService` has zero dependency on `atlasboxpy_controller` or any other package's exception hierarchy — it works the same whether or not the layer above it exists at all (a background worker calling a service directly, say). | — |
| Debuggability | The traceback reaching a controller (or any other caller) is the *original* one — nothing rewraps or truncates it — while the service-layer log line records exactly where it was first observed, with its own duration/context. | A bug that raises deep inside a long orchestration chain produces one ERROR log line per `BaseService` layer it passes through unhandled (each wrap along the way logs it once) — the same exception, logged multiple times at different layers; a log aggregator needs to correlate by exception identity/traceback, not just count log lines. |
| Evolvability | Adding error handling above `BaseService` (a new controller, a new worker type) never requires a change here — the contract is "you get the real exception," stable regardless of what's built on top. | — |

---

## ADR-3: `gather_named` propagates the first exception; no partial-success mode

**Context.** `gather_named` runs several named awaitables concurrently
— the generalized form of the `asyncio.gather(...)` calls this
ecosystem's own example app hand-wrote per call site before this helper
existed. `asyncio.gather` itself supports `return_exceptions=True`,
which would let `gather_named` return a mix of results and exceptions
instead of raising.

**Decision.** `gather_named` always propagates the first exception
raised by any of its calls (`return_exceptions=False`, `asyncio.gather`'s
own default) — it never returns a dict mixing real results with caught
exceptions.

**Alternatives considered**
- `return_exceptions=True`, handing back `{name: result_or_exception}`
  — technically more information preserved, but it turns every caller
  of `gather_named` into code that has to check each value's type
  before using it, defeating the point of a helper meant to *remove*
  per-call-site boilerplate. It also means a caller could accidentally
  treat a caught exception as a legitimate result if it forgets the
  check — a silent-partial-success failure mode this ecosystem has
  specifically avoided elsewhere (multi-entity writes in
  `examples/fastapi_kanban` fail loudly rather than leaving a
  half-applied state unreported — see that app's own ADR-1 and its
  `delete_board` ordering fix).
- A configurable `return_exceptions` parameter, deferring the choice to
  the caller — more flexible, but doubles the API surface for a
  behavior this package has one clear, considered opinion about; a
  caller who genuinely needs partial results can call `asyncio.gather`
  directly with the flag instead of asking `gather_named` to support
  both modes.
- Chosen: one behavior, matching `asyncio.gather`'s own default — an
  orchestrated operation where one leg fails is a failure of the whole
  operation.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | — | — |
| Portability | Every `gather_named` call site has the same, single failure semantics to reason about — no per-call-site decision about which mode to use. | A caller that genuinely wants "run these, tell me which ones failed, keep going" has to reach for `asyncio.gather(..., return_exceptions=True)` directly — `gather_named` doesn't cover that case at all. |
| Debuggability | A failing concurrent call is logged individually (which name, what exception) before the exception propagates — the failure is attributable to a specific named call, not just "something in this gather failed." | Only the *first* exception (in completion order, not call order) propagates and is visible to the caller as the raised exception — a second, independent failure among the same concurrent calls is still logged individually but doesn't itself propagate. |
| Evolvability | New concurrent call sites default to the same "any failure is a failure" behavior automatically — no per-site decision to get wrong. | — |
