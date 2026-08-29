# Extending validator_gateway

## Custom exceptions and status mappings

Subclass `DomainError` (or one of its built-in subclasses) and give it a
distinct `code`:

```python
from validator_gateway import DomainError, register_status_mapping

class QuotaExceededError(DomainError):
    code = "quota_exceeded"
    default_message = "Account quota exceeded."
    retryable = False  # retrying without upgrading the plan can't succeed

register_status_mapping(QuotaExceededError, http_status=402, grpc_status="RESOURCE_EXHAUSTED")
```

`register_status_mapping` is the only supported way to give a custom exception
its own HTTP/gRPC status — there's no dict to edit inside the package. Once
registered:

- `resolve_status(QuotaExceededError())` and `status_for_code("quota_exceeded")`
  both return the mapping you registered.
- `known_codes()` includes `"quota_exceeded"`.
- A recovery policy file (see [`recovery_policies.md`](recovery_policies.md)) can
  reference `"quota_exceeded"` as a key.

You don't need to call `register_status_mapping` at all if you're happy with
the mapping your exception inherits via its parent class — `resolve_status`
walks the MRO, so a subclass with no explicit entry falls back to its nearest
mapped ancestor (this is exactly how `AlreadyExistsError` gets `ConflictError`'s
409/`ALREADY_EXISTS` mapping without its own entry).

## Custom exception hooks

`on_exception` is any `Callable[[DomainError], None]`. `default_logging_hook()`
covers the common case (`WARNING` for 4xx-mapped codes, `ERROR` for 5xx-mapped
ones); wire in Sentry, OpenTelemetry, or anything else with `chain_hooks`:

```python
from validator_gateway import ValidatorGateway, default_logging_hook, chain_hooks

def notify_sentry(exc):
    import sentry_sdk
    sentry_sdk.capture_exception(exc.cause or exc)

gateway = ValidatorGateway(
    controller=UserController(user_service),
    on_exception=chain_hooks(default_logging_hook(), notify_sentry),
)
```

`chain_hooks` runs every hook even if an earlier one raises — a broken Sentry
call is logged and swallowed, never allowed to break `handle()`'s response.

## The OpenAPI registry

A "thin" route — one that doesn't type its body as a Pydantic model, e.g.
because it validates the payload itself via `gateway.controller` — hides its
real request shape from FastAPI's automatic OpenAPI generation. `ModelRegistry`
fills that gap without changing the handler's signature:

```python
from validator_gateway.registry import ModelRegistry
from validator_gateway.fastapi_integration import apply_registry_to_route, iter_api_routes

registry = ModelRegistry()

@registry.register("POST", "/users", CreateUserRequest, raises=[AlreadyExistsError])
async def create_user(request: Request, gateway=Depends(gateway_dep)):
    payload = CreateUserRequest.model_validate(await request.json())
    result = await gateway.handle(gateway.controller.create_user, payload)
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
