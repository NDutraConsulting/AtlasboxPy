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
or `ErrorResponse` — never a raw exception. A controller orchestrates
services — it constructs its own with no arguments and never references a
persistence-layer type; each method takes a single `props` dict, which it
validates for itself via `validate_props`:

```python
from pydantic import BaseModel
from atlasboxpy_controller import BaseController, NotFoundError, validate_props

class GetUserProps(BaseModel):
    user_id: str

class UserController(BaseController):
    def __init__(self) -> None:
        super().__init__()
        self.user_service = UserService()

    async def get_user(self, props: dict):
        payload = validate_props(GetUserProps, props)
        user = await self.user_service.find(payload.user_id)
        if user is None:
            raise NotFoundError(f"User {payload.user_id} not found")
        return user
```

Raising a `DomainError` (as above) is a convenience escape hatch — a failed
`validate_props` call raises `ValidationFailedError` this same way. The
preferred style once a method has a real service backing it is to build the
response directly — see [`extending.md`](extending.md).

## 2. Wrap it in a FastAPI route

The route extracts `props` from the request and calls the controller —
nothing else. It never builds a payload object or imports `GetUserProps`;
the controller method above is the only place that shape is declared.

```python
from fastapi import APIRouter, FastAPI, Request
from atlasboxpy_controller.fastapi_integration import extract_api_request, format_json_response

app = FastAPI()
router = APIRouter()
controller = UserController()

@router.get("/users/{user_id}")
async def get_user(request: Request):
    return await format_json_response(controller.get_user(await extract_api_request(request)))

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

{"status":"not-found","response_code":404,"error":{"code":"not_found","message":"User does-not-exist not found","details":{}}}
```

No `try/except` in the route, no manual `HTTPException` — `BaseController`
caught the `NotFoundError`, formatted it, and `to_json_response` used
`response_code` (set from `DomainError`'s built-in status table) directly
as the HTTP status. `status`/`response_code` are the same two fields an
agent or worker reads in-process, with no HTTP round trip needed — see
[`docs/architecture.md`](architecture.md).

A success call comes back the same shape, just with `status: "success"`,
`response_code: 200`, and a `data` field instead of `error`:

```bash
curl localhost:8000/users/123
# {"status":"success","response_code":200,"data":{"id":"123", ...}}
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
