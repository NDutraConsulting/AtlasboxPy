# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Renamed — `validator_gateway` is now `atlasboxpy_controller`

The package and its import path are renamed to better reflect what it
actually does since the `ValidatorGateway`/`handle()` removal below: it's
not a gateway anymore, it's a portable `BaseController` base class you can
reuse unmodified from an API route, a worker, or an agent, with consistent
error-handling behavior built in. `pip install atlasboxpy_controller`; CLI
is now `atlasboxpy-controller`. A companion package,
`atlasboxpy_repository` (`packages/atlasboxpy_repository/`), was split out
at the same time — a `BaseRepository` with a pluggable, read-through
cache. Both are flat, independently-named packages (no shared Python
namespace) — see the two packages' own READMEs.

### Changed — replaced `ValidatorGateway`/`handle()` with automatic controller wrapping

The gateway object is gone. `BaseController` (and its more primitive base,
`ExceptionFormatter`) now wraps every public async method on a subclass
automatically, at class-definition time, via `__init_subclass__`. Calling a
method directly — `await controller.get_user(user_id)` — already returns a
`SuccessResponse`/`ErrorResponse`; there's no gateway to construct and no
`handle()` call.

Rationale: the gateway's only real jobs were formatting responses and
logging failures, and per-request gateway construction (`get_gateway(request)`
closures repeated per feature) didn't scale as an app grew past one
feature. Deciding *what a failure means* — a hint message, a degraded
fallback — always belonged to the controller, since only the controller
knows what each of its own methods can fail at; routing that decision
through an external classifier (`ClassifyingValidatorGateway`) duplicated
knowledge the controller already had.

- Added `ExceptionFormatter` / `BaseController` (`controller.py`) — see
  `docs/extending.md`.
- Added `hide_internal_errors` (class attribute on `ExceptionFormatter`,
  default `True`) replacing `GatewayConfig`.
- Added `DomainErrorRoute` (renamed from `GatewayRoute`) — same
  belt-and-suspenders behavior, updated name to match: there's no gateway
  concept left to bypass.
- Removed `ValidatorGateway`, `gateway.py`, `on_exception`/`on_complete`
  hooks, `ExceptionHook`/`chain_hooks`/`default_logging_hook`
  (`logging.py`) — failure logging is now built into `BaseController` via
  `self.logger`.
- Removed the recovery/redirect engine (`recovery/`, `RecoveryEngine`,
  `JSONFilePolicyStore`, policy files) and `classifying.py`
  (`ClassifyingValidatorGateway`, `SourceJson`) — retry/redirect/queue
  policy and per-code classification are no longer part of this package;
  build them on top of `BaseController` if you need them.
- Removed `get_gateway_factory` (`fastapi_integration`) — construct your
  controller directly instead.
- `validator-gateway init` / `add-feature` now scaffold only a
  `{name}_controller.py` (no more paired `{name}_validator_gateway.py`).

### Added

- Domain exception hierarchy (`DomainError` and subclasses) with HTTP/gRPC status mapping.
- `SuccessResponse` / `ErrorResponse` envelope models, `build_error_response`.
- `ResponseStatus` enum and a `response_code` (100-999) field on both
  envelope models — a transport-agnostic status/code an in-process caller
  (a worker, an agent) reads directly, with no HTTP round trip, alongside
  the existing `http_status`/`grpc_status` mapping. `to_json_response`
  uses `response_code` directly as the HTTP status. New `TimedOutError`,
  `OutOfMemoryError`, `StackOverflowError` domain errors; `BaseController`
  now also catches `RecursionError`/`MemoryError` specifically (mapped to
  the latter two) instead of folding them into a generic unexpected-error
  response. `register_status_mapping` gained optional `response_code`/
  `response_status` keyword arguments.
- `validate_props(model, props)` — validates a plain `props` dict against
  a Pydantic model from inside a controller method, raising
  `ValidationFailedError` (not pydantic's own `ValidationError`) on a
  shape mismatch, so `BaseController`'s existing `DomainError` handling
  formats it. Lets a controller method's own model be the full contract
  for what a call needs, instead of a route validating a payload object
  before ever calling the controller.
- `fastapi_integration.extract_api_request(request)` /
  `format_json_response(coro)` — merge a request's path params, query
  params, and JSON body into one `props` dict, and convert an awaited
  controller call straight into a `JSONResponse`, so a route reduces to
  `return await format_json_response(controller.some_method(await extract_api_request(request)))`
  with no payload object built in the route.
