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

## Classifying gateways — an opt-in alternative to `ValidatorGateway`

The default `ValidatorGateway` treats every `DomainError` the same way:
`build_error_response(exc)`. Most gateways want that. Some don't — a
gateway that needs per-code custom messaging, or that wants to redirect a
specific failure to a *different* gateway (not just a registered fallback
callable, an actual second `ValidatorGateway`), can subclass
`validator_gateway.classifying.ClassifyingValidatorGateway` instead:

```python
from enum import Enum
from validator_gateway import DomainError, default_logging_hook
from validator_gateway.classifying import ClassifyingValidatorGateway, SourceJson
from validator_gateway.responses import build_error_response

class FailureCase(Enum):
    NOT_FOUND = "not_found"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"

class UserValidatorGateway(ClassifyingValidatorGateway[UserController]):
    _KNOWN_CASES: dict[str, Enum] = {"not_found": FailureCase.NOT_FOUND}

    def __init__(self, service, *, source_json: SourceJson) -> None:
        super().__init__(UserController(service), source_json=source_json,
                          on_exception=default_logging_hook())

    def _severity_fallback(self, is_server_error: bool) -> Enum:
        return FailureCase.SERVER_ERROR if is_server_error else FailureCase.CLIENT_ERROR

    async def _resolve(self, case, exc, action, args):
        match case:
            case FailureCase.NOT_FOUND:
                return build_error_response(exc)  # or custom messaging, or a redirect
            case _:
                return build_error_response(exc)
```

`_severity_fallback` and `_resolve` are `abstractmethod`s — a subclass that
doesn't implement both cannot be instantiated at all, so the classification
logic can never be silently skipped. `_classify()` checks your `_KNOWN_CASES`
map first (the recategorization layer you extend); anything not listed
there falls back to `_severity_fallback()`, decided purely from the
exception's mapped HTTP status via `resolve_status()` — nobody has to
predict every edge case up front for it to still get *some* sane bucket. A
raw non-`DomainError` exception (a bug, not a business-rule failure) never
reaches `_resolve()` at all; `handle()` reports it as `"unclassified"`
directly.

`source_json` (a `SourceJson(url, caller_type, method=None)`) is required,
not inferred — the caller must declare its own identity. `method` is
optional because a worker or agent calling the gateway directly has no
REST verb to report; an HTTP route generally supplies all three.

Every call is logged via `logging.getLogger("validator_gateway.traffic")`
— one line per call, success and failure alike, carrying `source_json`,
the method name, the classified case, and the request/response JSON. This
is separate from `on_exception` (which only ever fires on failure): point
a handler at that logger name to send it wherever you like.

`validator-gateway add-feature <name>` scaffolds a starting
`{name}_controller.py` + `{name}_validator_gateway.py` pair built on this
base, so you don't hand-write the skeleton above for every new feature —
see [`examples/fastapi_kanban`](../examples/fastapi_kanban) for a complete
worked example, including a redirect to a different gateway.

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
