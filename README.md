# validator_gateway

**One enforced call path into your business logic — for REST routes, background workers, agents, and gRPC servicers alike — with consistent error handling, formatted responses, and pluggable exception logging.**

```
frontend > thin api_route <-> ValidatorGateway <-> Controller <-> [services...] <-> [repository, model]
                                     ^
                     workers / agents / gRPC call in here directly, too
```

---

## Motivation

Most projects end up with error handling that's correct in spirit but inconsistent in practice: one endpoint raises `HTTPException`, another lets a `ValueError` bubble into a raw 500, a worker script wraps its call in a bare `try/except` that swallows the traceback, and an agent tool call gets whatever the underlying function happened to raise. Pydantic validates *structure* well, but it can't validate business rules asynchronously, and none of this gives you one consistent response shape across every caller.

`validator_gateway` exists to make that consistency structural instead of aspirational:

- **One call path.** Every controller invocation goes through `gateway.handle()`. There's no supported way to call a controller and skip the formatting and error handling — it's enforced at the gateway, not left to each route/worker/agent to remember.
- **One response shape.** Every call returns a typed `SuccessResponse` or `ErrorResponse`, whether the caller is an HTTP route, a queue worker, or an agent — never a raw exception, never a bespoke dict.
- **One exception vocabulary.** A small `DomainError` hierarchy (`NotFoundError`, `ConflictError`, `PermissionDeniedError`, ...) carries its own HTTP status and gRPC status mapping, so services never need to know which transport is calling them.
- **One place to hook observability.** Exception logging (or Sentry/OTel/whatever) plugs in once, at the gateway, and every caller gets it for free.
- **Recovery that isn't duplicated per caller.** Workers and agents often want to retry, redirect to a fallback, or queue-and-retry-later on failure — a synchronous HTTP request usually doesn't. `validator_gateway` supports both from the *same* controller: a REST route builds a fail-fast gateway, a worker builds one with a policy-driven `RecoveryEngine` attached, and neither duplicates the other's logic.

The core has no dependency on any specific transport, so a gRPC servicer or an agent's tool-calling loop uses it exactly the same way a FastAPI route does — construct the gateway, call `handle()`, done.

---

## Installation

```bash
pip install validator_gateway
```

If you're using it inside a FastAPI app (dependency injection, custom `APIRoute`, OpenAPI schema tooling):

```bash
pip install "validator_gateway[fastapi]"
```

For local development on this repo itself:

```bash
git clone <repo-url>
cd validator_gateway
pip install -e ".[dev]"
```

---

## Usage

### 1. Define domain exceptions and a controller

```python
from validator_gateway import BaseController, NotFoundError

class UserController(BaseController):
    def __init__(self, user_service):
        super().__init__()
        self.user_service = user_service

    async def get_user(self, user_id: str):
        user = await self.user_service.find(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user
```

### 2. Wrap it in a gateway and call through `handle()`

```python
from validator_gateway import ValidatorGateway, default_logging_hook

gateway = ValidatorGateway(
    controller=UserController(user_service),
    on_exception=default_logging_hook(),
)

response = await gateway.handle(gateway.controller.get_user, "123")
# -> SuccessResponse(data=<User>) or ErrorResponse(error=...)
# Never a raw exception, no matter what the controller or service raised.
```

### 3. Use it from FastAPI

```python
from fastapi import APIRouter, Depends
from validator_gateway.fastapi_integration import get_gateway_factory, to_json_response

router = APIRouter()
gateway_dep = get_gateway_factory(lambda: UserController(user_service))

@router.get("/users/{user_id}")
async def get_user(user_id: str, gateway=Depends(gateway_dep)):
    result = await gateway.handle(gateway.controller.get_user, user_id)
    return to_json_response(result)
```

A request for a missing user automatically comes back as an HTTP `404` with a formatted `ErrorResponse` body — no `try/except` in the route, no manual `HTTPException`.

### 4. Use it from a worker or agent — same gateway, no REST involved

```python
from validator_gateway import ValidatorGateway
from validator_gateway.recovery import RecoveryEngine, JSONFilePolicyStore

engine = RecoveryEngine(policy_store=JSONFilePolicyStore("validator_gateway.json"))
gateway = ValidatorGateway(controller=UserController(user_service), recovery=engine)

result = await gateway.handle(gateway.controller.get_user, "123")
```

Attach a `RecoveryEngine` and the same controller can retry on transient failures, redirect to a fallback, or hand off to a queue — driven entirely by a policy file (`validator_gateway.json`), matched against the same `DomainError.code` your controller already raises. No new code path, no duplicated logic between the REST route and the worker.

### 5. Use it from anywhere else (gRPC, CLI, agent tool call)

```python
gateway = ValidatorGateway(controller=UserController(user_service))
result = await gateway.handle(gateway.controller.get_user, request.user_id)

if result.status == "error":
    context.set_code(resolve_status_from_code(result.error.code).grpc_status)
```

The core package has no dependency on FastAPI or any other framework, so this works the same way regardless of what's calling it.

---

## Documentation

- [`docs/quickstart.md`](docs/quickstart.md) — install and stand up your first endpoint
- [`docs/architecture.md`](docs/architecture.md) — the request lifecycle and why the gateway enforces the controller relationship
- [`docs/extending.md`](docs/extending.md) — custom exceptions, custom exception hooks, OpenAPI registry integration
- [`docs/recovery_policies.md`](docs/recovery_policies.md) — retry / redirect / queue policy files for workers and agents

## License

See [`LICENSE`](LICENSE).
