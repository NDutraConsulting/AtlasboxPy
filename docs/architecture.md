# Architecture

## The request lifecycle

```
frontend > thin api_route <-> ValidatorGateway <-> Controller <-> [services...] <-> [repository, model]
                                     ^
                     workers / agents / gRPC call in here directly, too
```

A call enters through whatever transport is in front of it — an HTTP route, a
queue worker picking up a job, an agent's tool-calling loop, or a gRPC
servicer method. Every one of those callers does the same three things:

1. Construct a `ValidatorGateway(controller, ...)`.
2. Call `await gateway.handle(gateway.controller.some_method, *args, **kwargs)`.
3. Do something transport-specific with the returned `SuccessResponse` or
   `ErrorResponse` — turn it into a `JSONResponse` (FastAPI), set a gRPC
   status code, log it and move to the next queue item, or hand it back to an
   LLM as a tool result.

Inside `handle()`:

```
handle(action, *args, **kwargs)
  -> refuse to run `action` unless it's a bound method of self.controller
  -> await action(*args, **kwargs)
       success -> SuccessResponse(data=result)
       DomainError raised -> notify the exception hook
                           -> recovery engine attached? try retry/redirect/queue
                           -> still failing -> ErrorResponse (via build_error_response)
       any other Exception -> wrapped into a generic DomainError, same ErrorResponse path
       SystemExit / KeyboardInterrupt -> propagates uncaught (P4-T3) — these
                                          aren't "the business logic failed",
                                          they're "the process is stopping"
```

And the reverse path for exceptions:

```
DomainError.code  --(resolve_status / status_for_code)-->  StatusMapping(http_status, grpc_status)
                                                                    |
                                          FastAPI: to_json_response maps http_status
                                          gRPC:    context.set_code(mapping.grpc_status)
```

Neither transport adapter needs to know anything about *why* a `NotFoundError`
maps to 404/`NOT_FOUND` — that's decided once, in `exceptions.py`, and every
caller gets it for free.

## Why the gateway enforces the controller relationship

The original design goal is a guarantee, not a convention: **every** consumer —
REST, worker, agent, or a gRPC servicer — gets a well-formatted response, no
matter which endpoint or call site invokes the controller. A guarantee that
depends on every developer remembering to wrap their route in a `try/except`
is not a guarantee; it's a lint rule someone will eventually forget.

So `ValidatorGateway` makes it structural instead of aspirational:

- `validate_controller()` runs at construction time (`P2-T2`), before
  anything else — you cannot get a `ValidatorGateway` instance wrapping
  something that doesn't look like a controller.
- `handle()` checks that `action.__self__ is self.controller` whenever
  `action` has a `__self__` at all (`P2-T3`) — you cannot accidentally call
  through gateway A into controller B's method.
- `handle()`'s `except Exception` clause is a catch-all boundary — nothing
  except `BaseException` subtypes like `SystemExit`/`KeyboardInterrupt`
  escapes uncaught (`P4-T3`).
- `GatewayRoute` (FastAPI-only, opt-in) is the belt-and-suspenders case: even
  if a developer forgets to call `gateway.handle()` in a route handler and
  raises a `DomainError` directly, the response still comes back formatted
  correctly (`P6-T3`).

None of this is enforced by code review or documentation — it's enforced by
the fact that there is no other supported way to get from "a controller
method raised something" to "a caller received a response."

## Worker and gRPC callers need no adapter package

Because the core (`exceptions.py`, `controller.py`, `gateway.py`,
`responses.py`, `config.py`, `logging.py`, `registry.py`, `recovery/`) has
zero dependency on FastAPI or any other transport library — enforced by a CI
guardrail, not just by convention — a worker script and a gRPC servicer use
the exact same four lines:

**Worker** (`examples/worker_recovery/main.py`):

```python
from validator_gateway import ValidatorGateway
from validator_gateway.recovery import RecoveryEngine, JSONFilePolicyStore

engine = RecoveryEngine(policy_store=JSONFilePolicyStore("validator_gateway.json"))
gateway = ValidatorGateway(controller=UserController(user_service), recovery=engine)
result = await gateway.handle(gateway.controller.get_user, "123")
```

**gRPC servicer method** (equivalent shape, no adapter package required):

```python
from validator_gateway import ValidatorGateway, status_for_code

gateway = ValidatorGateway(controller=UserController(user_service))
result = await gateway.handle(gateway.controller.get_user, request.user_id)

if result.status == "error":
    context.set_code(status_for_code(result.error.code).grpc_status)
```

Same controller, same `handle()` call, same response shape. The only thing
that differs between a REST route, a worker, and a gRPC servicer is what each
one does with the `SuccessResponse`/`ErrorResponse` it gets back — never how
it gets one.

## Recovery is opt-in, per gateway instance

A synchronous HTTP request usually wants fail-fast behavior — the client is
waiting. A worker or agent usually wants retry, a fallback, or a queue
handoff. `validator_gateway` supports both from the *same* controller: build
one `ValidatorGateway` with no `recovery=` for the REST route, and a second
one with a `RecoveryEngine` attached for the worker — see
[`recovery_policies.md`](recovery_policies.md) for the full step vocabulary.
