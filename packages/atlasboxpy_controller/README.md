# atlasboxpy_controller

**Formatted, consistent error handling for your business logic — for REST routes, background workers, agents, and gRPC servicers alike — with no gateway object, no per-method decorator, and no `try/except` in your routes.**

```
frontend > thin api_route <-> Controller (BaseController) <-> [services...] <-> [repository, model]
                                     ^
                     workers / agents / gRPC call the controller directly, too
```

---

## Motivation

Most projects end up with error handling that's correct in spirit but inconsistent in practice: one endpoint raises `HTTPException`, another lets a `ValueError` bubble into a raw 500, a worker script wraps its call in a bare `try/except` that swallows the traceback, and an agent tool call gets whatever the underlying function happened to raise. Pydantic validates *structure* well, but it can't validate business rules asynchronously, and none of this gives you one consistent response shape across every caller.

`atlasboxpy_controller` exists to make that consistency structural instead of aspirational:

- **One response shape, automatically.** Subclass `BaseController` and every public async method is wrapped, at class-definition time, so a call always comes back as a typed `SuccessResponse` or `ErrorResponse` — never a raw exception. No gateway object, no per-method decorator.
- **One exception vocabulary.** A small `DomainError` hierarchy (`NotFoundError`, `ConflictError`, `PermissionDeniedError`, ...) carries its own HTTP status and gRPC status mapping, so services never need to know which transport is calling them.
- **The controller decides what a failure means.** An expected outcome — "not found", "validation failed" — is built directly as a response by the method that knows the context, not raised as control flow and classified by something external. `BaseController`'s wrapping is the safety net underneath that: whatever a service didn't already translate.
- **Zero framework coupling.** The core has no dependency on FastAPI or any other transport library, so a worker, an agent's tool-calling loop, or a gRPC servicer calls a controller exactly the same way an HTTP route does.

---

## Installation

> **This is a prototype/example project — it is not published to PyPI and there's no plan to.** The `pip install` commands below are illustrative only; install from a local clone (see below) to actually use it.

```bash
pip install atlasboxpy_controller
```

If you're using it inside a FastAPI app (`to_json_response`, OpenAPI registry tooling, the `DomainErrorRoute` belt-and-suspenders class):

```bash
pip install "atlasboxpy_controller[fastapi]"
```

For local development on this repo itself:

```bash
git clone <repo-url>
cd atlasboxpy_controller
pip install -e ".[dev]"
```

---

## Usage

### 1. Define a controller

A controller orchestrates services — nothing more. It constructs its own
service(s) with no arguments, and never references a persistence-layer
type (a DB session, an engine, a client): that's the service's concern
(and its repository's, further down). However a service resolves what it
needs — a config module, a DI container, an app-level default it reads at
construction time — is up to your app; the controller doesn't know and
doesn't need to.

Each public method takes one argument, `props` — a plain dict — and
validates it for itself via `validate_props`, against a Pydantic model
that IS the method's contract. The preferred style from there: build and
return `SuccessResponse`/`ErrorResponse` directly — an expected outcome is
data, not something to raise.

```python
from pydantic import BaseModel
from atlasboxpy_controller import BaseController, NotFoundError, SuccessResponse, build_error_response, validate_props

class GetUserProps(BaseModel):
    user_id: str

class UserController(BaseController):
    def __init__(self) -> None:
        super().__init__()
        self.user_service = UserService()  # resolves its own dependencies

    async def get_user(self, props: dict):
        payload = validate_props(GetUserProps, props)
        user = await self.user_service.find(payload.user_id)
        if user is None:
            return build_error_response(NotFoundError(f"User {payload.user_id} not found"))
        return SuccessResponse(data=user)
```

Raising a `DomainError` still works, as a convenience escape hatch for anything simpler — `BaseController` catches it and formats it the same way (a failed `validate_props` call raises `ValidationFailedError` this same way):

```python
    async def get_user(self, props: dict):
        payload = validate_props(GetUserProps, props)
        user = await self.user_service.find(payload.user_id)
        if user is None:
            raise NotFoundError(f"User {payload.user_id} not found")
        return user
```

### 2. Call it directly — no gateway, no `handle()`

```python
response = await UserController().get_user({"user_id": "123"})
# -> SuccessResponse(data=<User>) or ErrorResponse(error=...)
# Never a raw exception, no matter what the controller or service raised.
```

### 3. Use it from FastAPI

The route never builds a payload object — it merges the request into a
`props` dict and calls the controller with nothing else. Reading the
controller method (above) is what tells you what the request needs, not
the route:

```python
from fastapi import APIRouter, Request
from atlasboxpy_controller.fastapi_integration import extract_api_request, format_json_response

router = APIRouter()
controller = UserController()

@router.get("/users/{user_id}")
async def get_user(request: Request):
    return await format_json_response(controller.get_user(await extract_api_request(request)))
```

A request for a missing user automatically comes back as an HTTP `404` with a formatted `ErrorResponse` body — no `try/except` in the route, no manual `HTTPException`, no Pydantic model imported into the route file at all.

### 4. Use it from a worker, agent, or gRPC servicer — same controller, no REST involved

```python
from atlasboxpy_controller import ErrorResponse, status_for_code

result = await UserController().get_user({"user_id": request.user_id})

if isinstance(result, ErrorResponse):
    # result.status ("not-found", "timeout", "exception", ...) and
    # result.response_code (100-999) are already on the envelope — an
    # agent or worker reads them directly, no HTTP round trip needed.
    context.set_code(status_for_code(result.error.code).grpc_status)
```

The core package has no dependency on FastAPI or any other framework, so this works the same way regardless of what's calling it — and `{"user_id": request.user_id}` is exactly the same shape of `props` dict the REST route above builds, just assembled by hand instead of by `extract_api_request`.

---

## Documentation

- [`docs/quickstart.md`](docs/quickstart.md) — install and stand up your first endpoint
- [`docs/architecture.md`](docs/architecture.md) — the request lifecycle and why `BaseController` wraps method calls structurally instead of by convention
- [`docs/extending.md`](docs/extending.md) — custom exceptions, `hide_internal_errors`, OpenAPI registry integration

## License

See [`LICENSE`](LICENSE).
