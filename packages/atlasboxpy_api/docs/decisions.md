# Architecture decisions

Lightweight ADRs for the choices in this package that a developer
evaluating or extending it would reasonably ask "why not the obvious
alternative?" about. Each one names what was actually considered and
rejected, not a strawman.

## Which decision applies to what you're doing

```
Threading a value through from an incoming request to code several
layers down?
│
├─ Tempted to store it in a module-level variable/global instead of a
│  RequestContext?
│    └─→ ADR-1: don't — a global is process-wide; two concurrent
│         requests on the same event loop can read or overwrite each
│         other's value. RequestContext (a ContextVar) gives each
│         request its own isolated view for free.
│
└─ Deciding where the header's value gets validated/allowlisted?
     └─→ ADR-2: not in this package. HeaderContextMiddleware hands the
          raw header value to a `resolve` function you supply — pair it
          with something like atlasboxpy_db's VariantRouter, whose
          resolve() already falls back to a safe default for anything
          unrecognized.
```

---

## ADR-1: `ContextVar`-backed `RequestContext`, not a module-level global

**Context.** The motivating use case — resolving a REST header into
"which database variant should this request use" — needs a value that's
readable from deep inside the call stack (a repository's storage
composition helper) without threading it through every function
signature in between. The `examples/fastapi_kanban` demo already has a
precedent for exactly this shape of problem: `db_simulation.py`'s
`set_simulation()`/`get_simulation()`, backed by module-level globals.

**Decision.** `RequestContext[T]` wraps `contextvars.ContextVar`, not a
plain module-level variable. `HeaderContextMiddleware` calls `.set()`
once per request (from the resolved header value) and `.reset()` in a
`finally` block once that request completes.

**Alternatives considered**
- A module-level global (mirroring `db_simulation.py`) — works for a
  *debug toggle* that's rare, deliberately mutated by an operator, and
  fine to serialize with a lock (see this repo's own fix for exactly
  that race, `atlasboxpy_db`'s and this session's `db_simulation.py`
  lock). It's the wrong shape for *every single request* needing its
  own value: a lock would force every concurrent request through this
  middleware to wait for the one ahead of it, just to read/write a
  process-wide variable — a real, avoidable throughput cost that a
  debug-only toggle never had to pay.
- Threading the resolved value as an explicit parameter through every
  function between the middleware and the code that needs it — the
  "correct" alternative in principle, but it means every repository
  constructor, every composition helper, gains a parameter it only
  exists to pass along, for a value that's genuinely request-scoped
  metadata, not a piece of that function's own logic.
- Chosen: `ContextVar`, which is asyncio's own built-in mechanism for
  exactly "state scoped to the current task tree, invisible to sibling
  tasks, correctly propagated through everything the current task
  `await`s."

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | No lock, no contention between concurrent requests — each task's `ContextVar.get()`/`.set()` touches only that task's own context, not shared mutable state. | A `ContextVar` per distinct piece of request-scoped data, not one shared dict — a second use case (say, a request id) is a second `RequestContext` instance, not a new key on an existing global. |
| Portability | Works identically under any ASGI server/framework — `contextvars` is stdlib, propagation through `await` is part of the coroutine protocol itself, not something Starlette/FastAPI specifically provide. | — |
| Debuggability | "What value is this request using" is answerable by calling `.get()` from anywhere in that request's call stack — no risk of reading a value another concurrent request just wrote. | A value read outside of any request's context (e.g. at import time, or from a background task not spawned from a request) silently returns `default` rather than raising — matches `contextvars.ContextVar`'s own behavior, but worth knowing rather than assuming `.get()` always reflects "the current request." |
| Evolvability | Adding a second request-scoped value later is a second `RequestContext` + a second middleware instance (or reusing `HeaderContextMiddleware` with a different header/resolver) — no change to the first one. | — |

---

## ADR-2: Header validation lives entirely outside this package

**Context.** A REST header selecting a DB variant (or any other
resource) is untrusted input from the moment it arrives. This package
could own validating it — an allowlist parameter, a regex, something —
directly in `HeaderContextMiddleware`.

**Decision.** `HeaderContextMiddleware` takes a `resolve: Callable[[str
| None], T]` and does nothing with the header value except hand it to
that function. What counts as valid, what the safe default is, and what
gets returned for an unrecognized value are entirely the caller's
concern — typically delegated to something purpose-built for exactly
that, like `atlasboxpy_db`'s `VariantRouter`.

**Alternatives considered**
- Building allowlist/validation logic directly into this middleware
  (e.g. a `valid_values: set[str]` parameter) — would work for the
  motivating case, but conflates two genuinely separate concerns: "how
  do I get a header's value into request-scoped context" (a transport
  concern, framework-agnostic) and "what does a valid value even mean
  for my app" (a domain concern — for the DB-routing case specifically,
  it's about which `DBQuantum`/`ShardRouter` to resolve to, not just
  whether a string is in a set). Bundling them would mean this package
  either becomes DB-aware (contradicting "no framework or domain
  dependency") or reimplements a worse version of `VariantRouter`.
- Chosen: total separation. This package is transport-layer plumbing;
  `resolve` is where a caller plugs in whatever domain-specific,
  safe-by-construction resolution logic it already has.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | — | — |
| Portability | This package has zero required dependencies and no opinion about what's being resolved — a header could select a DB variant, a feature flag, a tenant, anything with a `Callable[[str \| None], T]` shape. | — |
| Debuggability | A bug in "which value did this header resolve to" is entirely in the caller's `resolve` function — one place to look, not split between this middleware and the caller's logic. | If a caller's `resolve` function isn't itself safe-by-default (unlike `VariantRouter`), this middleware provides no safety net — it will faithfully expose whatever `resolve` returns, including a mistake. |
| Evolvability | Swapping the resolution strategy (a different `VariantRouter` config, a completely different lookup) never touches this package. | — |
