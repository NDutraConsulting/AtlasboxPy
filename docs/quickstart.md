# Quickstart

## Install

```bash
pip install "validator_gateway[fastapi]"
```

(Drop `[fastapi]` if you're only using `validator_gateway` from a worker, agent, or
gRPC servicer — the core has no FastAPI dependency at all.)

## 1. Define a domain exception and a controller

Controllers raise `DomainError` subclasses. They know nothing about HTTP status
codes, response envelopes, or who's calling them.

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

## 2. Wrap it in a FastAPI route

```python
from fastapi import APIRouter, Depends, FastAPI
from validator_gateway import ValidatorGateway, default_logging_hook
from validator_gateway.fastapi_integration import get_gateway_factory, to_json_response

app = FastAPI()
router = APIRouter()
gateway_dep = get_gateway_factory(
    lambda: UserController(user_service), on_exception=default_logging_hook()
)

@router.get("/users/{user_id}")
async def get_user(user_id: str, gateway: ValidatorGateway = Depends(gateway_dep)):
    result = await gateway.handle(gateway.controller.get_user, user_id)
    return to_json_response(result)

app.include_router(router)
```

## 3. Run it

```bash
uvicorn myapp:app --reload
```

## 4. See a formatted error

```bash
curl -i localhost:8000/users/does-not-exist
```

```
HTTP/1.1 404 Not Found
content-type: application/json

{"status":"error","error":{"code":"not_found","message":"User does-not-exist not found","details":{}}}
```

No `try/except` in the route, no manual `HTTPException` — `gateway.handle()` caught
the `NotFoundError`, formatted it, and `to_json_response` mapped it to the correct
HTTP status via `DomainError`'s built-in status table.

A success call comes back the same shape, just with `status: "success"` and a
`data` field instead of `error`:

```bash
curl localhost:8000/users/123
# {"status":"success","data":{"id":"123", ...}}
```

## Scaffolding a new project

Once the Phase 11 CLI ships, `validator-gateway init` will generate starter
`controllers/` and `validator_gateways/` directories in the current project —
see the build plan's Phase 11 for the planned shape. Until then, the layout
shown above (a `controllers.py`/`services.py` split, one gateway per
controller) is the pattern every example in this repo follows.

## Where to go next

- [`architecture.md`](architecture.md) — the request lifecycle, and why the gateway
  enforces the controller relationship structurally instead of by convention.
- [`extending.md`](extending.md) — custom exceptions, custom logging hooks, the
  OpenAPI registry.
- [`recovery_policies.md`](recovery_policies.md) — retry/redirect/queue recovery for
  workers and agents.
- [`examples/fastapi_basic`](../examples/fastapi_basic) — a complete runnable CRUD app.
- [`examples/worker_recovery`](../examples/worker_recovery) — the same exception
  hierarchy recovering via a `RecoveryEngine`, with zero HTTP involved.
