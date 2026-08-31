# Extending atlasboxpy_controller

## Custom exceptions and status mappings

Subclass `DomainError` (or one of its built-in subclasses) and give it a
distinct `code`:

```python
from atlasboxpy_controller import DomainError, register_status_mapping

class QuotaExceededError(DomainError):
    code = "quota_exceeded"
    default_message = "Account quota exceeded."
    retryable = False  # retrying without upgrading the plan can't succeed

register_status_mapping(
    QuotaExceededError,
    http_status=402,
    grpc_status="RESOURCE_EXHAUSTED",
    response_code=402,               # optional — defaults to http_status
    response_status=ResponseStatus.ERROR,  # optional — defaults to ERROR
)
```

`register_status_mapping` is the only supported way to give a custom exception
its own HTTP/gRPC status — there's no dict to edit inside the package.
`response_code`/`response_status` are the values that land on the
`ErrorResponse` envelope itself (`response_code` must be in `[100, 999]`);
they're keyword-only and optional so an existing 3-arg call site keeps
working unchanged. Once registered:

- `resolve_status(QuotaExceededError())` and `status_for_code("quota_exceeded")`
  both return the mapping you registered.
- `known_codes()` includes `"quota_exceeded"`.

You don't need to call `register_status_mapping` at all if you're happy with
the mapping your exception inherits via its parent class — `resolve_status`
walks the MRO, so a subclass with no explicit entry falls back to its nearest
mapped ancestor (this is exactly how `AlreadyExistsError` gets `ConflictError`'s
409/`ALREADY_EXISTS` mapping without its own entry).

## Validating request props inside the controller

A controller method takes one argument, `props` — a plain `dict[str, Any]`
— and validates it for itself, via `validate_props`, against a Pydantic
model that IS the method's contract:

```python
from pydantic import BaseModel
from atlasboxpy_controller import ValidationFailedError, validate_props

class CreateUserProps(BaseModel):
    name: str
    email: str

class UserController(BaseController):
    async def create_user(self, props: dict) -> SuccessResponse | ErrorResponse:
        payload = validate_props(CreateUserProps, props)
        ...
```

`validate_props` raises `ValidationFailedError` (not pydantic's own
`ValidationError`) on a shape mismatch — `BaseController`'s existing
`DomainError` handling formats that into a response the same way it
formats any other raised `DomainError`, so the method needs no
`try/except` of its own.

This is deliberately *not* validation done by the route before the
controller is ever called: reading a controller method next to its model
tells you exactly what a call needs. A route file that only ever extracts
and forwards `props` has no opinion on shape at all — see
[`fastapi_integration.extract_api_request`](#calling-it-from-fastapi-with-no-payload-object-in-the-route)
below.

`validate_props` has no transport dependency — a worker or an agent
building the same `props` dict by hand gets identical validation, with no
FastAPI/Starlette involved at all.

### Calling it from FastAPI with no payload object in the route

`extract_api_request(request)` merges a request's query params, JSON
body, and path params into one flat `props` dict (path params win on a
name collision); `format_json_response(coro)` awaits a controller call and
converts the result straight into a `JSONResponse`:

```python
from fastapi import APIRouter, Request
from atlasboxpy_controller.fastapi_integration import extract_api_request, format_json_response

router = APIRouter()

@router.post("/users")
async def create_user(request: Request):
    return await format_json_response(controller.create_user(await extract_api_request(request)))
```

The route never imports `CreateUserProps` (or any Pydantic model at all) —
there's nothing left in the route to keep in sync with the controller's
contract.

### A controller orchestrates services, not the other way around

A controller's constructor takes no arguments and never references a
persistence-layer type — that's the service's concern, and its
repository's below that. Nothing outside the controller should construct
a service and hand it across that boundary, and the controller itself
shouldn't need to know how the service gets its data (a session factory,
a client, config):

```python
class UserController(BaseController):
    def __init__(self) -> None:
        super().__init__()
        self.user_service = UserService()  # resolves its own dependencies
```

How `UserService` resolves what it needs is up to your app — a config
module, a DI container, an app-level default it reads at construction
time (see `examples/fastapi_kanban/db.py`'s
`set_default_session_factory`/`get_default_session_factory` for one
concrete way to do this without threading a persistence type through
every constructor between the app entry point and the repository that
actually needs it). Testability doesn't suffer for this — a test still
controls what the service ultimately talks to; it just does so at the
layer that actually needs it, not by handing the controller something it
has no use for itself.

## How `BaseController` formats responses

`BaseController` (and its more primitive base, `ExceptionFormatter`) wraps
every public async method defined directly on a subclass, at
class-definition time, via `__init_subclass__`. Calling the method always
returns a `SuccessResponse` or `ErrorResponse`:

- If the method already returns one of those, it's passed through
  unchanged.
- If it returns a plain value, that becomes `SuccessResponse(data=value)`.
- If it raises a `DomainError`, that's formatted into an `ErrorResponse`
  and logged through `self.logger` (`BaseController` sets this up for you;
  `WARNING` for a 4xx-mapped code, `ERROR` for 5xx).
- If it raises anything else, it's treated as a bug: wrapped into a generic
  `DomainError` and formatted the same way, with the real message replaced
  by `"An unexpected error occurred."` unless the subclass sets
  `hide_internal_errors = False`.
- `SystemExit`/`KeyboardInterrupt` are never caught — those mean the process
  is stopping, not that a business rule failed.

Leading-underscore methods (`_response_for`, `_validate_title`, ...) are
left untouched — they're internal helpers, not entrypoints, and calling one
directly returns whatever it actually returns.

### Two styles for an expected outcome

**Raising** is the simplest thing to reach for, and is fully supported as a
convenience escape hatch:

```python
class UserController(BaseController):
    async def get_user(self, props: dict):
        payload = validate_props(GetUserProps, props)
        user = await self.user_service.find(payload.user_id)
        if user is None:
            raise NotFoundError(f"User {payload.user_id} not found")
        return user
```

**Building the response directly** is the preferred style once a method has
real service-layer outcomes to translate — an expected business outcome
like "not found" is data, not something to raise and unwind the stack for:

```python
from atlasboxpy_controller import ErrorResponse, SuccessResponse, build_error_response, validate_props

class UserController(BaseController):
    async def get_user(self, props: dict) -> SuccessResponse | ErrorResponse:
        payload = validate_props(GetUserProps, props)
        result = await self.user_service.find(payload.user_id)  # a ServiceResult, say
        if result.status != ServiceStatus.SUCCESS:
            return build_error_response(NotFoundError(result.msg))
        return SuccessResponse(data=result.data)
```

`build_error_response(exc)` never raises `exc` — it just reads its `code`,
`message`, and `details` to build the response. This is also how a
controller method decides what a failure means for *that* method
specifically — a scenario-specific hint appended to a message, or a
degraded fallback returned in place of an error — since the response is
just a value the method can inspect and modify before returning:

```python
async def create_board(self, props: dict) -> SuccessResponse | ErrorResponse:
    payload = validate_props(CreateBoardRequest, props)
    response = self._response_for(await self.service.create_board(payload.name))
    if isinstance(response, ErrorResponse) and response.error.code == "validation_failed":
        response.error.message += " (hint: every board starts with 3 default columns)"
    return response
```

See [`examples/fastapi_kanban`](../../examples/fastapi_kanban)'s
`KanbanController` for a complete worked example, including a degraded
fallback for a failed read (`get_board`) that a write gets no such
treatment for.

`atlasboxpy-controller add-feature <name>` scaffolds a starting
`{name}_controller.py` built on `BaseController`, so you don't hand-write
the class skeleton for every new feature.

## The OpenAPI registry

A "thin" route — one that doesn't type its body as a Pydantic model, e.g.
because it validates the payload itself — hides its real request shape from
FastAPI's automatic OpenAPI generation. `ModelRegistry` fills that gap
without changing the handler's signature:

```python
from atlasboxpy_controller.registry import ModelRegistry
from atlasboxpy_controller.fastapi_integration import apply_registry_to_route, iter_api_routes

registry = ModelRegistry()

@registry.register("POST", "/users", CreateUserRequest, raises=[AlreadyExistsError])
async def create_user(request: Request):
    payload = CreateUserRequest.model_validate(await request.json())
    result = await controller.create_user(payload)
    return to_json_response(result)

# after building the app/router, before the first app.openapi() call:
for route in iter_api_routes(app.routes):
    apply_registry_to_route(route, registry)
```

Registering the same `(method, path)` twice raises `ValueError` unless you pass
`overwrite=True` — this is meant to catch an accidental duplicate registration,
not to support silently swapping schemas.

Use `iter_api_routes(app.routes)`, not a bare `isinstance(route, APIRoute)` loop
over `app.routes` — depending on the installed FastAPI version, routes added via
`app.include_router(...)` aren't always plain `APIRoute` entries in `app.routes`
directly; `iter_api_routes` recurses through however the version you have wraps
them.

`raises=[...]` on `@registry.register` documents which `DomainError` subclasses
the endpoint can raise; `apply_registry_to_route` turns that into `responses`
entries in the generated OpenAPI doc, each one embedding `ErrorResponse`'s JSON
schema, keyed by the HTTP status each exception maps to.

For an app with many registered models, `build_custom_openapi(app, registry)`
(Level 3) replaces `app.openapi()` entirely, using
`pydantic.json_schema.models_json_schema()` so two models sharing a nested
submodel dedupe to one `components/schemas` entry instead of two independently
embedded copies.

## `DomainErrorRoute` — belt-and-suspenders for a bypassed controller

If a `DomainError` is ever raised directly inside a route handler — before
reaching a `BaseController` method that would have formatted it —
`APIRouter(route_class=DomainErrorRoute)` catches and formats it anyway:

```python
from fastapi import APIRouter
from atlasboxpy_controller.fastapi_integration import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)
```

This changes nothing for a handler whose `DomainError`s already come from a
`BaseController` method, since those never escape unformatted in the first
place.
