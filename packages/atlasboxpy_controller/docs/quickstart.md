# Quickstart

## Install

```bash
pip install "atlasboxpy_controller[fastapi]"
```

(Drop `[fastapi]` if you're only using `atlasboxpy_controller` from a worker, agent, or
gRPC servicer — the core has no FastAPI dependency at all.)

## 1. Define a controller

Subclass `BaseController`. Its public async methods are wrapped automatically
at class-definition time, so calling one always returns a `SuccessResponse`
or `ErrorResponse` — never a raw exception.

```python
from atlasboxpy_controller import BaseController, NotFoundError

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

Raising a `DomainError` (as above) is a convenience escape hatch. The
preferred style once a method has a real service backing it is to build the
response directly — see [`extending.md`](extending.md).

## 2. Wrap it in a FastAPI route

```python
from fastapi import APIRouter, FastAPI
from atlasboxpy_controller.fastapi_integration import to_json_response

app = FastAPI()
router = APIRouter()
controller = UserController(user_service)

@router.get("/users/{user_id}")
async def get_user(user_id: str):
    result = await controller.get_user(user_id)
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

No `try/except` in the route, no manual `HTTPException` — `BaseController`
caught the `NotFoundError`, formatted it, and `to_json_response` mapped it to
the correct HTTP status via `DomainError`'s built-in status table.

A success call comes back the same shape, just with `status: "success"` and a
`data` field instead of `error`:

```bash
curl localhost:8000/users/123
# {"status":"success","data":{"id":"123", ...}}
```

## Scaffolding a new project

```bash
atlasboxpy-controller init
```

generates a starter `controllers/` directory in the current project.
`atlasboxpy-controller add-feature <name>` scaffolds a `{name}_controller.py` for
a new feature the same way. See `examples/fastapi_scaffolded` for the
generated output wired into a real FastAPI app.

## Where to go next

- [`architecture.md`](architecture.md) — the request lifecycle, and why `BaseController`
  wraps method calls structurally instead of by convention.
- [`extending.md`](extending.md) — custom exceptions, `hide_internal_errors`, the
  OpenAPI registry.
- [`examples/fastapi_basic`](../../examples/fastapi_basic) — a complete runnable CRUD app.
- [`examples/fastapi_kanban`](../../examples/fastapi_kanban) — a fuller app (Starlette + SQLite)
  showing scenario-specific hints and a degraded-response fallback, both decided inline
  by the controller.
