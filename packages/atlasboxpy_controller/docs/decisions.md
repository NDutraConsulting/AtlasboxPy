# Architecture decisions

Lightweight ADRs for the choices in this package that a developer
evaluating or extending it would reasonably ask "why not the obvious
alternative?" about. Each one names what was actually considered and
rejected, not a strawman.

## Which decision applies to what you're doing

```
Building or changing a BaseController subclass?
│
├─ Where should request validation happen?
│    └─→ ADR-3: inside the method, via validate_props(Model, props) —
│         never in the route, never in a separate validation layer.
│
├─ How do I report an expected failure ("not found", "title too long")?
│    └─→ ADR-2: build/return an ErrorResponse directly (or raise a
│         DomainError as a shortcut) — never a framework-specific
│         exception like FastAPI's HTTPException.
│
├─ Does my controller need a new service or other dependency?
│    └─→ ADR-4: construct it yourself, in __init__ — don't accept a
│         pre-built instance from whoever's constructing the controller.
│
└─ Do I need to wrap this method in a try/except so a bug doesn't leak
   a raw, unformatted 500?
     └─→ ADR-1: no — BaseController already wraps every public method
          structurally. Write the happy path only.
```

---

## ADR-1: Structural response wrapping via `__init_subclass__`, not a decorator or a gateway object

**Context.** Every controller method must guarantee it returns a
`SuccessResponse`/`ErrorResponse`, never a raw exception, regardless of
which transport calls it. This package's predecessor (`ValidatorGateway`/
`handle()`, removed — see `CHANGELOG.md`) required constructing a gateway
object and calling `.handle(method, *args)`, a step a route could forget
or apply inconsistently.

**Decision.** `ExceptionFormatter.__init_subclass__` rewrites every public
async method on a `BaseController` subclass at class-definition time,
wrapping it in the try/except once. Calling the method directly already
returns the formatted envelope — no extra step.

**Alternatives considered**
- Manual `try/except` in every route — easy to forget, duplicated per
  route, and `hide_internal_errors` handling would need reimplementing
  everywhere it's forgotten.
- A `@handle_errors` decorator on each method — the same protection, but
  opt-in per method; a new method without the decorator silently loses
  the guarantee.
- A gateway object with `.handle(method, *args)` — what this package
  replaced. An indirection between "call something" and "call the
  controller," and one more object every call site has to construct.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | Wrapping happens once, at class-definition time, not per call; runtime cost per call is just the try/except itself. | One extra coroutine frame (`wrapper`) per call — negligible outside genuinely hot paths. |
| Portability | No framework/transport dependency — a worker, an agent, or a gRPC servicer gets the same guarantee for free by subclassing `BaseController`. | — |
| Debuggability | `functools.wraps` preserves the real method's name/signature, so tracebacks point at it, not an opaque wrapper. A dropped guarantee is structurally impossible — one less class of bug to chase. | The wrapping is invisible from reading the class body alone; a developer unfamiliar with `__init_subclass__` has to know to look in `controller.py`. |
| Evolvability | A new public async method on any subclass is wrapped automatically, no boilerplate to remember. | An internal helper must be named with a leading underscore to opt out — a convention to learn, not something the type system enforces. |

---

## ADR-2: A response envelope carrying its own `status`/`response_code`, not raise-and-let-each-transport-map

**Context.** An error needs to tell an in-process caller (a worker, an
agent) what happened without an HTTP round trip, *and* give a REST caller
a correct HTTP status. Raising a typed exception and letting each
transport adapter catch and map it means duplicating that mapping logic
once per transport, and an in-process caller still has to catch an
exception rather than read a value off an object it already has.

**Decision.** `DomainError` carries a `code`; `resolve_status()` maps that
once to `(http_status, grpc_status, response_code, response_status)`;
`build_error_response` copies `response_code`/`status` onto the
`ErrorResponse` envelope itself, so every caller — in-process or over
HTTP — reads the same two fields.

**Alternatives considered**
- Raise, let each transport catch and map — a new `DomainError` subclass
  needs its mapping added in N places (one per transport adapter), not one.
- Return a raw framework `Response` object from the controller — couples
  the controller to one specific transport, defeating "same method, any
  caller."
- Chosen: embed `status`/`response_code` on the envelope, decided once at
  the exception layer.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | One dict lookup (`resolve_status`) per error, done once, not once per transport. | Every response, even a plain success, now carries two extra fields — trivial serialization cost. |
| Portability | A worker or agent branches on `result.status`/`result.response_code` with zero HTTP dependency; the same envelope crosses REST, gRPC, and in-process calls unchanged. | — |
| Debuggability | A test or REPL session calls a controller method directly and reads the exact verdict a deployed REST caller would see, with no server running. | Two "status" concepts now exist (`response_code`/`status` on the envelope vs. `http_status`/`grpc_status` on `StatusMapping`) — a newcomer has to learn they're deliberately different, not duplicates. |
| Evolvability | A new status (`out-of-memory`, `stack-overflow`) is one `_STATUS_MAP` entry plus one `DomainError` subclass; every existing transport adapter picks it up for free. | `response_code`'s range and vocabulary are this package's own invention, not a standard like HTTP — a new team member learns it from these docs, not prior REST experience. |

---

## ADR-3: `validate_props` inside the controller method, not in the route

**Context.** Validating a request body in the route (FastAPI's automatic
Pydantic-in-signature binding, or a hand-rolled `validate_body` step
before the controller is called) means the request's real shape is
declared in the route file — and a worker or agent calling the controller
directly bypasses that validation, or has to duplicate it.

**Decision.** Every controller method takes one argument, `props: dict`,
and validates it itself via `validate_props(Model, props)`, which raises
`ValidationFailedError` — handled by the same `BaseController` wrapping as
any other domain error.

**Alternatives considered**
- FastAPI's automatic body-to-model binding on the route signature — ties
  validation to FastAPI specifically; a worker calling the same
  controller method gets no validation unless it reimplements it.
- A standalone "validation layer" module between the route and the
  controller — the contract lives in a third file, separate from both the
  route and the method that actually uses the validated data.
- Chosen: `validate_props` inside the method — the model IS the method's
  contract, in one place.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | Same one `model_validate` call as any other approach — no added cost from where it happens. | — |
| Portability | A REST route, a worker, and an agent all get identical validation from the same `props` dict shape; none re-implements or skips it. | — |
| Debuggability | Reading one method (and the one model it names) tells you everything a call needs — no jumping between a route file and a controller to reconstruct the contract. | A validation failure's traceback points inside `validate_props`/`model_validate`, one frame further from the route than a route-level FastAPI validation error would be. |
| Evolvability | Adding a field to a request is a one-line change to one Pydantic model, next to the method that uses it — nothing in the route changes. | Every route must remember to funnel the whole request into `props` (via `extract_api_request`) rather than picking out path params by hand — a convention, not something enforced on the route side. |

---

## ADR-4: A controller constructs its own service(s), not injected pre-built

**Context.** A composition root wiring `service = SomeService(deps);
controller = SomeController(service)` has to know how to construct every
service a controller needs — persistence types, config, everything — even
though the controller itself never touches any of that directly.

**Decision.** `SomeController.__init__(self) -> None: self.service =
SomeService()` — zero arguments, constructs its own service. Whatever the
service needs to resolve its own dependencies is that service's (and its
repository's) problem, not the controller's or the composition root's.

**Alternatives considered**
- A DI container/framework resolving constructor dependencies
  automatically — real machinery for what's usually a small, fixed
  dependency graph at this scale.
- Manual injection at the composition root
  (`SomeController(SomeService(session_factory))`) — forces the
  composition root to know a persistence-layer type just to relay it,
  when nothing at that layer actually uses it.
- Chosen: each layer constructs the layer below it; one genuinely shared
  piece of config (which database) is registered once and resolved by
  the one class that actually needs it — see
  `examples/fastapi_kanban/db.py`'s `get_default_session_factory`.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | No difference — construction cost is the same regardless of who calls the constructor. | — |
| Portability | A controller is fully self-contained: `SomeController()` works identically in a test, a script, or the real app, with no wiring code to carry along. | — |
| Debuggability | Fewer moving pieces to trace — dependencies aren't scattered across whoever happened to construct the controller. | The "shared, settable default" mechanism this pattern leans on is itself a small piece of implicit, process-global state — you have to know it exists and when it was last set. |
| Evolvability | Adding a dependency to the service never touches the controller's constructor or any call site that constructs one. | Doesn't generalize automatically to per-request dependencies (a request-scoped tenant, say) the way a DI framework's scoped providers would — each new per-request need is threaded through `props` by hand. |
