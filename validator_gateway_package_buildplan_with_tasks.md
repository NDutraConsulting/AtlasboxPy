# `validator_gateway` — Package Build Plan

**Audience:** AI coding agent building this repository task-by-task.
**Goal:** A reusable, pip-installable Python package that developers `import` into their FastAPI projects (and, symmetrically, into workers and agents that never touch HTTP at all) to enforce a strict **ValidatorGateway → Controller** relationship, with try/except-wrapped controller calls, consistently formatted success/error responses, a pluggable exception-logging hook, and an optional, policy-driven recovery/redirect engine for non-request/response callers.

Work through the phases in order. Each task has a **Do** (what to build), a **File(s)** (where it lives), and an **Acceptance** (how to know it's done). Do not skip ahead — later phases assume earlier phases are complete and tested. Commit after each completed task with a message matching the task ID (e.g. `feat(P1-T2): add DomainError hierarchy`).

---

## Design Decisions (fixed — do not deviate without flagging)

1. **Package name:** `validator_gateway`, importable as `import validator_gateway`.
2. **Layout:** `src/` layout (`src/validator_gateway/...`), not flat layout. Required for correct packaging and to avoid accidental local-import shadowing during tests.
3. **Python support:** 3.10+ (needed for modern generics / `X | Y` unions / `match`-`case`).
4. **Dependency posture:** `pydantic>=2.0` is a hard dependency. `fastapi` is an **optional extra** (`pip install validator_gateway[fastapi]`) — the core gateway/exception/response/recovery logic must be framework-agnostic so *any* caller can construct a `ValidatorGateway` directly and get identical behavior: an HTTP route, a background worker, an agent, or a gRPC servicer. No transport-specific adapter package is required for non-HTTP callers — a gRPC handler instantiates the gateway and calls `handle()` exactly like the worker example does, and maps the result's status using `resolve_status(exc).grpc_status` (Phase 1), which already exists for this purpose.
5. **Core relationship being enforced:** A `ValidatorGateway` may only be constructed with a `controller` that satisfies the `Controller` protocol (Phase 2). Constructing a gateway with a non-conforming object must raise `TypeError` immediately — not fail silently, not fail on first call.
6. **Single call path:** All controller invocation happens through `gateway.handle(...)`. There must be no supported way to call a controller method that bypasses the gateway's try/except and response formatting — this is the entire value proposition of the package and must be enforced structurally (see P2-T3), not just documented. This holds identically whether the caller is an HTTP route, a queue worker, or an agent tool call.
7. **Response envelope:** every successful `handle()` call returns a `SuccessResponse[T]`; every failed call returns an `ErrorResponse` built from a domain exception. Both are Pydantic models. No raw dicts, no bare exceptions escaping `handle()` except truly unrecoverable ones explicitly opted into (see P4-T3).
8. **Recovery is opt-in, per gateway instance.** A synchronous HTTP request generally wants fail-fast behavior (the client is waiting); a worker or agent generally wants retry/redirect/queue behavior. The *same controller* can be wrapped by two differently configured `ValidatorGateway` instances — one with no `recovery` engine (REST), one with a `RecoveryEngine` attached (worker/agent) — without duplicating controller code.
9. **Recovery policy is data, dispatch is code.** `validator_gateway.json` (or a future DB-backed store) declares *which* recovery steps apply to *which* `DomainError.code`. It never names arbitrary importable code paths. Redirect targets resolve only through a static allowlist registered in Python at gateway construction time.

---

## Phase 0 — Repository Scaffolding

- [x] **P0-T1: Initialize project structure**
  **Do:** Create the repo skeleton below. Empty `__init__.py` files may be stubs for now.
  ```
  validator_gateway/
    pyproject.toml
    README.md
    LICENSE
    CHANGELOG.md
    .gitignore
    src/validator_gateway/
      __init__.py
      exceptions.py
      controller.py
      gateway.py
      responses.py
      logging.py
      config.py
      registry.py
      cli.py
      recovery/
        __init__.py
        models.py
        policy_store.py
        engine.py
      fastapi_integration/
        __init__.py
        dependency.py
        route.py
        exception_handlers.py
        openapi.py
    examples/
      fastapi_basic/
        main.py
        controllers.py
        services.py
        models.py
        tests/
          test_api.py
      worker_recovery/
        main.py
        validator_gateway.json
      fastapi_scaffolded/
        # generated via `validator-gateway init`, plus hand-written glue (Phase 12)
        tests/
          test_api.py
      fastapi_recovery/
        main.py
        validator_gateway.json
        tests/
          test_api.py
    tests/
      __init__.py
      test_exceptions.py
      test_gateway.py
      test_responses.py
      test_config.py
      test_logging.py
      test_recovery.py
      test_fastapi_integration.py
      test_openapi_registry.py
      test_cli.py
    docs/
      quickstart.md
      architecture.md
      extending.md
      recovery_policies.md
      schemas/
        policy.schema.json
  ```
  **File(s):** whole tree.
  **Acceptance:** `tree` output matches the above; `pip install -e .` succeeds with no source files beyond stubs.

- [x] **P0-T2: `pyproject.toml`**
  **Do:** Use `hatchling` (or `setuptools>=68` with `src` layout) as build backend. Declare:
  - `name = "validator_gateway"`, semantic version starting at `0.1.0`
  - `dependencies = ["pydantic>=2.0,<3.0"]`
  - `[project.optional-dependencies] fastapi = ["fastapi>=0.100"]`, `dev = ["pytest", "pytest-cov", "httpx", "ruff", "mypy", "fastapi", "uvicorn"]`
  - `[project.urls]` placeholders for Homepage/Repository/Issues
  **File(s):** `pyproject.toml`
  **Acceptance:** `pip install -e ".[dev]"` installs cleanly; `python -c "import validator_gateway"` works.

- [x] **P0-T3: Tooling config**
  **Do:** Add `ruff` config (line length 100, enable `E,F,I,UP`) and `mypy` config (`strict = true` for `src/`, relaxed for `tests/` and `examples/`) either in `pyproject.toml` or dedicated files. Add a `.gitignore` covering `__pycache__/`, `.venv/`, `*.egg-info/`, `.mypy_cache/`, `.pytest_cache/`, `dist/`.
  **File(s):** `pyproject.toml` (or `ruff.toml`, `mypy.ini`), `.gitignore`
  **Acceptance:** `ruff check .` and `mypy src/` run without configuration errors (failures on empty stubs are fine at this stage).

- [x] **P0-T4: CI workflow**
  **Do:** GitHub Actions workflow that on push/PR: installs `.[dev]`, runs `ruff check .`, `mypy src/`, `pytest --cov=validator_gateway --cov-report=term-missing`. Matrix over Python 3.10/3.11/3.12.
  **File(s):** `.github/workflows/ci.yml`
  **Acceptance:** Workflow file is valid YAML and runs green on an empty-but-importable package.

---

## Phase 1 — Domain Exception Hierarchy

This is the vocabulary every other phase builds on. Controllers/services raise these; they know nothing about HTTP, gRPC, retries, or queues.

- [x] **P1-T1: Base `DomainError`**
  **Do:** Define the root exception with a stable machine-readable `code`, a human `message`, an optional `details: dict | None` for structured context (e.g. which field failed), and an optional `cause: Exception | None` for chaining.
  ```python
  class DomainError(Exception):
      code: str = "domain_error"
      default_message: str = "A domain error occurred."
      retryable: bool = True  # see P1-T5

      def __init__(self, message: str | None = None, *, details: dict | None = None, cause: Exception | None = None):
          self.message = message or self.default_message
          self.details = details or {}
          self.cause = cause
          super().__init__(self.message)
  ```
  **File(s):** `src/validator_gateway/exceptions.py`
  **Acceptance:** Unit test constructs `DomainError()` with defaults and with all kwargs; `str(err)` returns the message; `err.cause` chains correctly via `raise X from cause`.

- [x] **P1-T2: Standard subclasses**
  **Do:** Define this minimum set, each with a distinct `code` and sensible `default_message`. This set intentionally mirrors both HTTP status families and gRPC status families so a single hierarchy drives both, from any caller, with no separate code path per transport:
  - `ValidationFailedError` (code `validation_failed`) — structural/semantic input validation failure not already caught by Pydantic
  - `NotFoundError` (code `not_found`)
  - `ConflictError` (code `conflict`)
  - `AlreadyExistsError` (code `already_exists`, subclass of `ConflictError`)
  - `PermissionDeniedError` (code `permission_denied`)
  - `UnauthenticatedError` (code `unauthenticated`)
  - `PreconditionFailedError` (code `precondition_failed`)
  - `RateLimitedError` (code `rate_limited`)
  - `UnprocessableError` (code `unprocessable`) — business rule violation on structurally valid input
  - `UpstreamServiceError` (code `upstream_error`) — a downstream dependency failed
  **File(s):** `src/validator_gateway/exceptions.py`
  **Acceptance:** Each subclass instantiates with no args and produces its `default_message`; each is a subclass of `DomainError`; `isinstance` checks pass for `AlreadyExistsError` against both `AlreadyExistsError` and `ConflictError`.

- [x] **P1-T3: Status-code mapping table**
  **Do:** A single source-of-truth mapping, not scattered `if/elif` chains, from exception class to `(http_status: int, grpc_status_name: str)`. Use a `dict[type[DomainError], StatusMapping]` with a lookup function that walks the MRO so subclasses inherit their parent's mapping unless overridden.
  ```python
  @dataclass(frozen=True)
  class StatusMapping:
      http_status: int
      grpc_status: str  # e.g. "NOT_FOUND"

  _STATUS_MAP: dict[type[DomainError], StatusMapping] = {
      DomainError: StatusMapping(500, "UNKNOWN"),
      ValidationFailedError: StatusMapping(422, "INVALID_ARGUMENT"),
      NotFoundError: StatusMapping(404, "NOT_FOUND"),
      ConflictError: StatusMapping(409, "ALREADY_EXISTS"),
      PermissionDeniedError: StatusMapping(403, "PERMISSION_DENIED"),
      UnauthenticatedError: StatusMapping(401, "UNAUTHENTICATED"),
      PreconditionFailedError: StatusMapping(412, "FAILED_PRECONDITION"),
      RateLimitedError: StatusMapping(429, "RESOURCE_EXHAUSTED"),
      UnprocessableError: StatusMapping(422, "FAILED_PRECONDITION"),
      UpstreamServiceError: StatusMapping(502, "UNAVAILABLE"),
  }

  def resolve_status(exc: DomainError) -> StatusMapping: ...
  ```
  This mapping is what lets a gRPC servicer (or any other non-HTTP caller) use the package with zero extra integration work — `resolve_status(exc).grpc_status` is usable immediately, no separate adapter package required.
  **File(s):** `src/validator_gateway/exceptions.py`
  **Acceptance:** Test a custom `class TooManyItemsError(ConflictError): pass` with no explicit map entry resolves to `ConflictError`'s mapping via MRO walk. Test every class in P1-T2 resolves to a distinct, correct mapping.

- [x] **P1-T4: Developer-extensibility for custom exceptions**
  **Do:** Public function `register_status_mapping(exc_type: type[DomainError], http_status: int, grpc_status: str) -> None` so downstream developers can register their own `DomainError` subclasses without editing package source. Also add `known_codes() -> set[str]` returning every registered code across built-ins and developer registrations — this is what Phase 5's policy loader validates against.
  **File(s):** `src/validator_gateway/exceptions.py`
  **Acceptance:** Test registers a new custom exception class + mapping from outside the package (simulate via a test-local subclass) and confirms `resolve_status` picks it up and `known_codes()` includes it.

- [x] **P1-T5: `retryable` classification**
  **Do:** Set `retryable = False` on `PermissionDeniedError`, `UnauthenticatedError`, and `ValidationFailedError` (retrying without changing the input/credentials cannot succeed). Leave `retryable = True` (the `DomainError` default) on the rest, including `UpstreamServiceError`, `RateLimitedError`, `PreconditionFailedError`, `ConflictError`/`AlreadyExistsError`, `UnprocessableError`, and `NotFoundError`. This flag is advisory metadata for Phase 5's policy validator, not enforced at raise time.
  **File(s):** `src/validator_gateway/exceptions.py`
  **Acceptance:** `PermissionDeniedError.retryable is False`; `UpstreamServiceError.retryable is True`; a subclass without an explicit override inherits its parent's value.

---

## Phase 2 — Controller Contract + Gateway Core

- [x] **P2-T1: `Controller` protocol**
  **Do:** Define a structural typing `Protocol` (not an ABC requiring inheritance — developers shouldn't be forced to inherit from a package base class for every controller) that a controller must satisfy. Minimum contract: controllers expose async callables. Also provide an optional `BaseController` ABC for developers who *do* want inheritance-based conventions (e.g. shared `self.logger`).
  ```python
  class Controller(Protocol):
      """Structural contract. Any object with async methods matching the
      (payload) -> result shape used in ValidatorGateway.handle() qualifies."""
      ...

  class BaseController(ABC):
      """Optional convenience base class."""
      def __init__(self, *, logger: logging.Logger | None = None):
          self.logger = logger or logging.getLogger(self.__class__.__module__)
  ```
  **File(s):** `src/validator_gateway/controller.py`
  **Acceptance:** A plain class with an `async def create_user(self, payload)` method satisfies `isinstance(obj, Controller)` under `runtime_checkable`, or passes a `validate_controller(obj)` helper if `Protocol` runtime-checking proves too loose (see P2-T2) — pick whichever technique below actually enforces intent, and justify the choice in a code comment.

- [x] **P2-T2: Controller validation at gateway construction**
  **Do:** Because a bare `Protocol` with only methods can be satisfied by almost anything, add an explicit `validate_controller(controller: object) -> None` function that:
  1. Confirms `controller` is not `None` and not a class (must be an instance).
  2. Confirms at least one public async method exists (`inspect.iscoroutinefunction`).
  3. Raises `TypeError` with a clear message listing what's wrong if checks fail.
  Call this from `ValidatorGateway.__init__` (P2-T3) before anything else.
  **File(s):** `src/validator_gateway/controller.py`
  **Acceptance:** Passing a plain `object()` raises `TypeError`. Passing a class with only sync methods raises `TypeError` with a message naming the missing requirement. Passing a valid async-method-bearing instance passes silently.

- [x] **P2-T3: `ValidatorGateway` base class — the core deliverable**
  **Do:** This is the central class of the package. Note the `recovery` constructor parameter is defined but left unused (`None`-only, no branching logic) in this phase — Phase 5 amends `handle()`'s except-block to consult it. Building it into the signature now avoids an awkward Phase 5 signature change.
  ```python
  T = TypeVar("T")

  class ValidatorGateway(Generic[T]):
      def __init__(
          self,
          controller: T,
          *,
          config: GatewayConfig | None = None,
          on_exception: ExceptionHook | None = None,
          recovery: "RecoveryEngine | None" = None,  # wired in Phase 5
      ) -> None:
          validate_controller(controller)
          self.controller = controller
          self.config = config or GatewayConfig()
          self._on_exception = on_exception
          self._recovery = recovery

      async def handle(
          self,
          action: Callable[..., Coroutine[Any, Any, Any]],
          *args: Any,
          **kwargs: Any,
      ) -> SuccessResponse[Any] | ErrorResponse:
          """The ONLY supported entrypoint for invoking a controller method."""
          try:
              result = await action(*args, **kwargs)
              return SuccessResponse(data=result)
          except DomainError as exc:
              self._notify(exc)
              return build_error_response(exc)
          except Exception as exc:  # noqa: BLE001 - intentional catch-all boundary
              wrapped = DomainError(
                  message="An unexpected error occurred." if self.config.hide_internal_errors else str(exc),
                  cause=exc,
              )
              self._notify(wrapped)
              return build_error_response(wrapped)

      def _notify(self, exc: DomainError) -> None:
          if self._on_exception is not None:
              self._on_exception(exc)
  ```
  Note `action` is expected to be a **bound method of `self.controller`** — add a runtime check that `action.__self__ is self.controller` when that attribute exists, and raise `ValueError` otherwise. This is what structurally enforces "you can't route around the gateway": `handle()` refuses to invoke anything that isn't a method of the controller it was constructed with. This also holds for worker/agent callers — they get the same enforcement, not a looser variant.
  **File(s):** `src/validator_gateway/gateway.py`
  **Acceptance:**
  - Calling `gateway.handle(gateway.controller.some_method, payload)` on success returns `SuccessResponse(data=...)`.
  - Raising a `NotFoundError` inside the controller method results in `handle()` returning (not raising) an `ErrorResponse` with `code="not_found"`.
  - Raising a bare `ValueError` inside the controller method is caught and wrapped into a generic `DomainError`-derived `ErrorResponse` — nothing escapes `handle()` uncaught.
  - Passing a method that belongs to a *different* object than `self.controller` raises `ValueError` before the method is invoked (test with a spy to confirm no side effect occurred).

- [x] **P2-T4: `GatewayConfig`**
  **Do:** Pydantic (or plain dataclass) settings object:
  ```python
  class GatewayConfig(BaseModel):
      hide_internal_errors: bool = True   # mask str(exc) for unexpected exceptions in prod
      include_traceback_in_details: bool = False  # dev-only aid, never default-on
      default_error_code_on_unexpected: str = "internal_error"
  ```
  **File(s):** `src/validator_gateway/config.py`
  **Acceptance:** Defaults are safe-for-production (no internals leaked). Test that `hide_internal_errors=False` surfaces `str(exc)` in the error response and `=True` (default) does not.

---

## Phase 3 — Response Envelope

- [x] **P3-T1: `SuccessResponse[T]` and `ErrorResponse`**
  **Do:**
  ```python
  class SuccessResponse(BaseModel, Generic[T]):
      status: Literal["success"] = "success"
      data: T

  class ErrorDetail(BaseModel):
      code: str
      message: str
      details: dict[str, Any] = Field(default_factory=dict)

  class ErrorResponse(BaseModel):
      status: Literal["error"] = "error"
      error: ErrorDetail
  ```
  **File(s):** `src/validator_gateway/responses.py`
  **Acceptance:** Both models serialize with `model_dump(mode="json")` to plain JSON-safe dicts. `SuccessResponse[UserOut](data=user)` validates `data` against `UserOut`.

- [x] **P3-T2: `build_error_response(exc: DomainError) -> ErrorResponse`**
  **Do:** Pure function, no framework dependency, using P1-T3's `resolve_status` only to inform HTTP-layer status codes later (P3 output itself carries no HTTP status — that's the transport adapter's job, see P6).
  **File(s):** `src/validator_gateway/responses.py`
  **Acceptance:** Given any `DomainError` subclass instance, returns an `ErrorResponse` whose `error.code`/`error.message`/`error.details` match the exception.

---

## Phase 4 — Exception Logging Hook

- [x] **P4-T1: `ExceptionHook` type + default no-op**
  **Do:** `ExceptionHook = Callable[[DomainError], None]`. Provide `default_logging_hook(logger: logging.Logger | None = None) -> ExceptionHook` that logs at `ERROR` for 5xx-mapped exceptions and `WARNING` for 4xx-mapped ones (use P1-T3's `resolve_status` to decide the level).
  **File(s):** `src/validator_gateway/logging.py`
  **Acceptance:** Passing `on_exception=default_logging_hook()` to `ValidatorGateway` logs a `NotFoundError` at WARNING and an unexpected wrapped exception at ERROR (assert via `caplog` in pytest).

- [x] **P4-T2: Composable hooks**
  **Do:** `chain_hooks(*hooks: ExceptionHook) -> ExceptionHook` so a developer can combine e.g. structured logging + a Sentry/OTel call without the package needing to know about either.
  **File(s):** `src/validator_gateway/logging.py`
  **Acceptance:** `chain_hooks(hook_a, hook_b)` calls both in order; if `hook_a` raises, `hook_b` still runs and the original exception from `handle()` flow is unaffected (hook failures must never break `handle()` — wrap each hook call in its own try/except inside `chain_hooks`, log hook failures at ERROR without re-raising).

- [x] **P4-T3: Escape hatch for non-`DomainError`, unrecoverable exceptions**
  **Do:** Document (and implement) that `BaseException` subtypes like `KeyboardInterrupt` and `SystemExit` are **not** caught by `handle()` — only `Exception` and below. Add an explicit test proving this.
  **File(s):** `src/validator_gateway/gateway.py`, `tests/test_gateway.py`
  **Acceptance:** Raising `SystemExit` inside a controller method propagates out of `handle()` uncaught.

---

## Phase 5 — Recovery & Redirect Policy Engine

This phase is what lets workers and agents call `handle()` directly and get automatic retry, fallback/redirect, or queue-based recovery — without any REST layer involved, and without changing how a fail-fast REST gateway behaves. It reuses `DomainError.code` (Phase 1) as the only dispatch key; no second taxonomy is introduced.

- [x] **P5-T1: Recovery data model**
  **Do:** Define the step vocabulary as Pydantic models, kept intentionally small and declarative:
  ```python
  class RecoveryAction(str, Enum):
      RETRY = "retry"
      REDIRECT = "redirect"
      QUEUE = "queue"
      FAIL = "fail"

  class RetrySpec(BaseModel):
      max_attempts: int = 3
      backoff_base_seconds: float = 0.5
      backoff_multiplier: float = 2.0
      jitter: bool = True

  class RedirectSpec(BaseModel):
      target: str  # a name registered via gateway.register_fallback(), NEVER a dotted import path

  class QueueSpec(BaseModel):
      queue_name: str
      max_delay_seconds: int | None = None

  class RecoveryStep(BaseModel):
      action: RecoveryAction
      retry: RetrySpec | None = None
      redirect: RedirectSpec | None = None
      queue: QueueSpec | None = None

  class QueuedJob(BaseModel):
      controller_class: str
      method_name: str
      args: list[Any]
      kwargs: dict[str, Any]
      original_code: str
      attempt_count: int
  ```
  A policy for a given code is `list[RecoveryStep]`, walked in order — this list *is* the "workflow transition": e.g. `[RETRY, REDIRECT, QUEUE]` means "retry first, redirect if retries are exhausted, queue if redirect also fails." `args`/`kwargs` on `QueuedJob` must be JSON-serializable; document this constraint prominently.
  **File(s):** `src/validator_gateway/recovery/models.py`
  **Acceptance:** All models round-trip through `model_dump_json()` / `model_validate_json()`. A policy list of 3 steps deserializes correctly from the example `validator_gateway.json` shape below (P5-T2).

- [x] **P5-T2: `PolicyStore` + `JSONFilePolicyStore` + JSON Schema**
  **Do:** Define the storage seam and one concrete implementation:
  ```python
  class PolicyStore(Protocol):
      def get_policy(self, code: str) -> list[RecoveryStep]: ...

  class JSONFilePolicyStore:
      def __init__(self, path: str | Path) -> None: ...
      def get_policy(self, code: str) -> list[RecoveryStep]: ...
  ```
  Example `validator_gateway.json`:
  ```json
  {
    "upstream_error": [
      {"action": "retry", "retry": {"max_attempts": 3, "backoff_base_seconds": 0.5}},
      {"action": "redirect", "redirect": {"target": "degraded_create_user"}},
      {"action": "queue", "queue": {"queue_name": "recovery.upstream_error"}}
    ],
    "rate_limited": [
      {"action": "retry", "retry": {"max_attempts": 5, "backoff_base_seconds": 1.0, "backoff_multiplier": 2.0}}
    ],
    "permission_denied": [
      {"action": "fail"}
    ]
  }
  ```
  At load time, `JSONFilePolicyStore` must validate every top-level key against `exceptions.known_codes()` (P1-T4) and raise a clear `PolicyValidationError` listing any unknown code (typo protection), and must reject any `RETRY` step whose code maps to a `DomainError` subclass with `retryable = False` (P1-T5), also via `PolicyValidationError`. Ship a JSON Schema for editor/CI validation of hand-authored policy files.
  **File(s):** `src/validator_gateway/recovery/policy_store.py`, `docs/schemas/policy.schema.json`
  **Acceptance:** Loading a file with an unknown code raises `PolicyValidationError` naming the bad key. Loading a file with `{"action": "retry"}` under `permission_denied` raises `PolicyValidationError` naming the non-retryable code. A well-formed file loads and `get_policy("upstream_error")` returns 3 `RecoveryStep` objects in order.

- [x] **P5-T3: `DBPolicyStore` — seam only**
  **Do:** Define the `Protocol` shape only (matches `PolicyStore`); do not implement a working database-backed store in this phase. Add a docstring explaining the intended shape (a table keyed by `code` storing a JSON blob of steps, same validation rules as P5-T2 applied on write, not just on read) so a developer can implement it later without redesigning the interface.
  **File(s):** `src/validator_gateway/recovery/policy_store.py`
  **Acceptance:** `DBPolicyStore` (or a documented note that `PolicyStore` itself is sufficient as the seam) exists and is referenced from `docs/recovery_policies.md`; no runtime behavior required.

- [x] **P5-T4: Redirect target allowlist (security-critical)**
  **Do:** Add `register_fallback(name: str, target: Callable[..., Coroutine]) -> None` on `ValidatorGateway`, storing entries in a private `dict[str, Callable]`. `RedirectSpec.target` values are resolved **only** through this dict at call time — never via `getattr` on an arbitrary string, `importlib`, or `eval`. Resolving an unregistered target must raise a clear error at the point the recovery engine first needs it (fail loud, not a silent no-op fallthrough to `FAIL`).
  **File(s):** `src/validator_gateway/gateway.py`
  **Acceptance:** A policy step naming a redirect target that was never registered raises a descriptive error when the recovery engine attempts to use it (test both: registered-and-resolves correctly, and unregistered-and-raises). Confirm via code review comment / test that no `importlib`, `eval`, or `getattr`-on-a-free-string path exists anywhere in the redirect resolution code.

- [x] **P5-T5: `RecoveryEngine` — match/case dispatch**
  **Do:** The engine walks a code's step list in order, executing each until one succeeds, using `match`/`case` on `RecoveryAction` as the dispatch mechanism (per your design). Enforce a hard cap on total steps executed across the whole chain (e.g. `max_total_steps: int = 10` config value) to prevent runaway loops regardless of how a policy file is authored.
  ```python
  class RecoveryEngine:
      def __init__(self, policy_store: PolicyStore, *, enqueue_hook: EnqueueHook | None = None, max_total_steps: int = 10):
          self._policy_store = policy_store
          self._enqueue_hook = enqueue_hook
          self._max_total_steps = max_total_steps

      async def recover(
          self,
          exc: DomainError,
          gateway: "ValidatorGateway",
          action: Callable[..., Coroutine],
          args: tuple,
          kwargs: dict,
      ) -> Any:
          steps = self._policy_store.get_policy(exc.code)
          total = 0
          for step in steps:
              total += 1
              if total > self._max_total_steps:
                  raise exc
              match step.action:
                  case RecoveryAction.RETRY:
                      try:
                          return await self._retry(step.retry, action, args, kwargs)
                      except DomainError:
                          continue  # exhausted retries -> next step in chain
                  case RecoveryAction.REDIRECT:
                      try:
                          target = gateway.resolve_fallback(step.redirect.target)
                          return await target(*args, **kwargs)
                      except DomainError:
                          continue
                  case RecoveryAction.QUEUE:
                      await self._enqueue(step.queue, exc, action, args, kwargs)
                      return None  # accepted for later processing, not a synchronous result
                  case RecoveryAction.FAIL:
                      raise exc
          raise exc  # steps exhausted with no FAIL step present
  ```
  **File(s):** `src/validator_gateway/recovery/engine.py`
  **Acceptance:** A 3-step policy `[RETRY(x2, always fails), REDIRECT(succeeds)]` returns the redirect's result, not an error. A policy where every step fails and no `FAIL` step is present ultimately re-raises the original exception rather than looping forever (verified against `max_total_steps`).

- [x] **P5-T6: `EnqueueHook` interface**
  **Do:** `EnqueueHook = Callable[[QueueSpec, QueuedJob], Awaitable[None]]`. The package ships no concrete queue backend (no bundled Celery/RQ/SQS client) — developers supply their own hook, matching the pattern already established for `ExceptionHook` in Phase 4.
  **File(s):** `src/validator_gateway/recovery/engine.py`
  **Acceptance:** A test `enqueue_hook` (an in-memory list append) receives a correctly populated `QueuedJob` when a `QUEUE` step executes, including a serializable `args`/`kwargs` payload and the correct `attempt_count`.

- [x] **P5-T7: Wire `RecoveryEngine` into `ValidatorGateway.handle()`**
  **Do:** Amend the `except DomainError as exc:` branch from P2-T3: if `self._recovery is not None`, call `await self._recovery.recover(exc, self, action, args, kwargs)` and wrap its result in `SuccessResponse`; if that raises (recovery exhausted or a `FAIL` step hit), fall through to the existing `build_error_response(exc)` path. If `self._recovery is None`, behavior is byte-for-byte identical to Phase 2 — this must not change default (REST) behavior for gateways that don't opt in.
  **File(s):** `src/validator_gateway/gateway.py`
  **Acceptance:** Two tests against the *same controller*: (1) a gateway with no `recovery` returns a formatted `ErrorResponse` immediately on `UpstreamServiceError`, no retries observed; (2) a gateway with a `RecoveryEngine` attached and a matching retry policy returns `SuccessResponse` after N simulated transient failures, and the underlying action was invoked the expected number of times.

- [x] **P5-T8: Transport-agnostic core guardrail**
  **Do:** Add a CI check (an `import-linter` contract, or a simple `ruff`/`grep`-based rule) that fails the build if `exceptions.py`, `controller.py`, `gateway.py`, `responses.py`, `config.py`, `logging.py`, `registry.py`, or anything under `recovery/` imports `fastapi` or any other transport-specific library. This is what makes "a gRPC servicer just instantiates `ValidatorGateway` directly" actually true rather than aspirational — it's enforced, not just documented. No `grpc_integration/` package, adapter, or forward-looking phase is needed: the core already accepts any caller.
  **File(s):** `.github/workflows/ci.yml` (or a dedicated `importlinter.toml` invoked from it)
  **Acceptance:** Introducing a stray `import fastapi` into `gateway.py` in a test branch causes CI to fail; removing it passes again. Core test suite (P8) requires no `fastapi` install to run — verify by running `pytest tests/ --ignore=tests/test_fastapi_integration.py --ignore=tests/test_openapi_registry.py` inside a venv where `fastapi` was never installed. (Use `--ignore`, not `-k "not fastapi_integration and not openapi_registry"` — `-k` only filters which collected tests run, it doesn't skip *collecting* those modules, so the excluded test file still gets imported and fails with `ModuleNotFoundError: fastapi` before any filtering happens.)

**Note for Phase 6:** REST routes will typically construct their `ValidatorGateway` **without** `recovery` (fail-fast, per Design Decision 8); workers/agents construct theirs **with** it. Both wrap the same controller instance or class.

---

## Phase 6 — FastAPI Integration (optional extra)

- [x] **P6-T1: Dependency-injection helper**
  **Do:** `get_gateway_factory(controller_factory: Callable[..., T], **gateway_kwargs) -> Callable[..., ValidatorGateway[T]]` returning a FastAPI-`Depends`-compatible callable, so routes can do:
  ```python
  gateway_dep = get_gateway_factory(lambda: UserController(user_service), on_exception=default_logging_hook())

  @router.post("/users")
  async def create_user(payload: CreateUserRequest, gateway: ValidatorGateway = Depends(gateway_dep)):
      result = await gateway.handle(gateway.controller.create_user, payload)
      return to_json_response(result)
  ```
  Deliberately omit a `recovery=` kwarg from the example above — per Design Decision 8, REST routes default to fail-fast. Document (docstring) how a developer would attach one anyway if they explicitly want retry-behind-a-slow-endpoint, but don't make it the example.
  **File(s):** `src/validator_gateway/fastapi_integration/dependency.py`
  **Acceptance:** Works with `fastapi.testclient.TestClient` against a minimal app; gateway is constructed fresh per-request (no shared mutable state across requests unless the developer's `controller_factory` deliberately returns a singleton).

- [x] **P6-T2: `to_json_response` — envelope → `Response`**
  **Do:** Convert a `SuccessResponse`/`ErrorResponse` into a `fastapi.responses.JSONResponse` with the correct HTTP status (200 for success unless overridden, mapped status via P1-T3 for errors).
  **File(s):** `src/validator_gateway/fastapi_integration/exception_handlers.py`
  **Acceptance:** A `NotFoundError` raised in a controller ends up as an HTTP 404 response body matching `ErrorResponse` shape, verified end-to-end via `TestClient`.

- [x] **P6-T3: `GatewayRoute` custom `APIRoute` (belt-and-suspenders)**
  **Do:** Provide an optional `APIRoute` subclass that catches any `DomainError` that somehow escapes a route handler (e.g. a developer forgot to route a call through `gateway.handle()`) and still formats it correctly, so the guarantee holds even under partial misuse. This must be explicitly **opt-in** (`router = APIRouter(route_class=GatewayRoute)`), not silently monkey-patched onto the app.
  **File(s):** `src/validator_gateway/fastapi_integration/route.py`
  **Acceptance:** A route handler that raises `DomainError` directly (bypassing `gateway.handle()`) still returns a correctly formatted `ErrorResponse` when using `GatewayRoute`; a plain `APIRoute` in the same test app does not (proves the opt-in adds real value, not just decoration).

- [x] **P6-T4: PATCH/partial-update helper**
  **Do:** `extract_patch_data(model: BaseModel) -> dict[str, Any]` thin wrapper over `model.model_dump(exclude_unset=True)`, exported from the FastAPI integration module with a docstring explaining the unset-vs-null problem from the design discussion, so developers don't have to rediscover it.
  **File(s):** `src/validator_gateway/fastapi_integration/dependency.py` (or a new `partial.py`)
  **Acceptance:** Test with a model where one field is explicitly `None` and another is omitted — only the omitted one is absent from the returned dict.

---

## Phase 7 — OpenAPI Extension Tooling

- [ ] **P7-T1: Model registry**
  **Do:** `ModelRegistry` (likely a classmethod-based registry on a small class, or a module-level singleton with a clear reset-for-tests function) mapping `(method, path) -> request_model type`, populated via a decorator:
  ```python
  @registry.register("POST", "/users", CreateUserRequest)
  async def create_user(...): ...
  ```
  **File(s):** `src/validator_gateway/registry.py`
  **Acceptance:** Registering two different models against the same `(method, path)` raises a clear error (fail loud on accidental duplicate registration) unless an explicit `overwrite=True` is passed.

- [ ] **P7-T2: `openapi_extra` injection helper (Level 2 integration)**
  **Do:** `apply_registry_to_route(route: APIRoute, registry: ModelRegistry) -> None` that sets `route.openapi_extra["requestBody"]` from the registered model's `model_json_schema()`.
  **File(s):** `src/validator_gateway/fastapi_integration/openapi.py`
  **Acceptance:** After calling this on a thin route with a request body that FastAPI otherwise couldn't introspect, `app.openapi()["paths"]["/users"]["post"]["requestBody"]` contains the correct schema.

- [ ] **P7-T3: Full custom `app.openapi()` builder (Level 3 integration)**
  **Do:** `build_custom_openapi(app: FastAPI, registry: ModelRegistry) -> dict`, using `pydantic.json_schema.models_json_schema()` (not per-model `.model_json_schema()` calls) to dedupe shared `$defs` and avoid ref collisions, matching FastAPI's `#/components/schemas/{model}` ref template.
  **File(s):** `src/validator_gateway/fastapi_integration/openapi.py`
  **Acceptance:** Two registered models sharing a nested submodel produce one `$defs` entry, not two; generated schema validates as OpenAPI 3.1 (use a lightweight validator like `openapi-spec-validator` in the test's dev-only dependency, or a hand-rolled structural check if avoiding the extra dependency).

- [ ] **P7-T4: Error-response schema in OpenAPI**
  **Do:** Ensure every registered path's OpenAPI operation includes `ErrorResponse` as the schema for its documented non-2xx responses (400/401/403/404/409/422/429/500 etc., per which `DomainError` subclasses the endpoint's controller method is documented to raise — add an optional `raises: list[type[DomainError]]` param to the `@registry.register` decorator for this purpose).
  **File(s):** `src/validator_gateway/registry.py`, `src/validator_gateway/fastapi_integration/openapi.py`
  **Acceptance:** A route registered with `raises=[NotFoundError, ConflictError]` shows `404` and `409` response schemas (both referencing `ErrorResponse`) in the generated OpenAPI doc.

---

## Phase 8 — Test Suite Completion

- [ ] **P8-T1: Unit test coverage ≥ 90%** across `exceptions.py`, `gateway.py`, `responses.py`, `config.py`, `logging.py`, `controller.py`, and everything under `recovery/`.
- [ ] **P8-T2: Integration test app** under `tests/` (separate from `examples/`) exercising a full request lifecycle: route → gateway → controller → service → repository (in-memory fake) → back through error/success formatting, for at least one success path and one path per major `DomainError` subclass.
- [ ] **P8-T3: Enforcement tests** — a dedicated `tests/test_enforcement.py` proving the "can't bypass the gateway" guarantees from P2-T3 and P6-T3 with adversarial/misuse-style test cases (wrong controller's method, sync method passed where async expected, calling `handle()` before construction completes, etc.).
- [ ] **P8-T4: Recovery engine coverage** — `tests/test_recovery.py` must cover: a full retry→redirect→queue chain where each step is exercised in order; a non-retryable code rejected at policy-load time; an unregistered redirect target rejected with a clear error rather than silently falling through; the `max_total_steps` guard actually terminating a pathological policy; and a REST-style gateway (`recovery=None`) provably making zero extra calls compared to a worker-style gateway (`recovery=RecoveryEngine(...)`) against the same failing controller method.

**Acceptance for the whole phase:** `pytest --cov` passes at ≥90% with no `# pragma: no cover` used to fake the number; CI (P0-T4) is green.

---

## Phase 9 — Documentation & Examples

- [ ] **P9-T1: `examples/fastapi_basic/`**
  **Do:** A minimal but complete runnable app: one resource (`User`), full CRUD, using `ValidatorGateway`, `BaseController`, a fake in-memory repository, `default_logging_hook`, and both a Level-1 (typed signature) route and one Level-2/3 (registry-driven) thin route to demonstrate both integration styles. This gateway is constructed **without** `recovery` (fail-fast REST). Must run via `uvicorn examples.fastapi_basic.main:app --reload` with zero additional setup beyond `pip install -e ".[fastapi]"`.
- [ ] **P9-T2: `examples/worker_recovery/`**
  **Do:** A standalone script (no FastAPI dependency) that constructs a `ValidatorGateway` around the *same kind of* controller as P9-T1 but **with** a `RecoveryEngine` loaded from a bundled `validator_gateway.json`, calls `gateway.handle(...)` directly in a loop simulating queued jobs, and prints which recovery step resolved each simulated failure. This is the concrete proof of the capability discussed in design: workers/agents call the gateway directly, with recovery, and no REST layer involved.
  **File(s):** `examples/worker_recovery/main.py`, `examples/worker_recovery/validator_gateway.json`
- [ ] **P9-T3: `docs/quickstart.md`** — install, minimal example, run it, see a formatted error response by hitting a 404 case.
- [ ] **P9-T4: `docs/architecture.md`** — the request lifecycle diagram in prose (`api_route → ValidatorGateway.handle() → Controller → Services → Repository/Model`, and the reverse path for exceptions), and *why* the gateway enforces the controller relationship (ties back to the original design goal: guarantee every consumer — REST, worker, agent, or a gRPC servicer — gets well-formatted responses, no matter which endpoint or call site invokes it). Include a short side-by-side: the same 4-line worker snippet from `examples/worker_recovery`, and an equivalent 4-line gRPC servicer method (`gateway = ValidatorGateway(controller); result = await gateway.handle(...)`, mapping `resolve_status(exc).grpc_status` onto `context.set_code(...)`), to make concrete that gRPC needs no adapter package.
- [ ] **P9-T5: `docs/extending.md`** — how to add a custom `DomainError` subclass + status mapping (P1-T4), how to add a custom exception hook (P4-T2), and how to use the OpenAPI registry (P7).
- [ ] **P9-T6: `docs/recovery_policies.md`** — the `validator_gateway.json` schema, the retry/redirect/queue step vocabulary, a worked example of a multi-step workflow transition chain, the `retryable` flag and why some codes reject `RETRY` at load time, and — prominently — the security rule that redirect targets only ever resolve through `register_fallback()`, never through dynamic import or eval of policy data. Cross-reference `DBPolicyStore` as the future seam for a database-backed policy source.
- [ ] **P9-T7: `README.md`** — short pitch, install instructions (`pip install validator_gateway[fastapi]`), 15-line "hello world" matching P9-T3's quickstart, links to `docs/`.

**Acceptance:** A developer with no prior context can `pip install -e ".[fastapi]"`, follow `README.md` alone, and get a working endpoint returning a formatted `ErrorResponse` for a 404 case in under 5 minutes. Separately, running `examples/worker_recovery/main.py` demonstrates at least one retry-recovers, one redirect-recovers, and one queue-handoff case using the bundled policy file.

---

## Phase 10 — Packaging & Release Readiness

- [ ] **P10-T1: Version + changelog discipline.** `CHANGELOG.md` follows Keep a Changelog format; version in `pyproject.toml` bumped to `0.1.0` for first release.
- [ ] **P10-T2: `LICENSE`.** Confirm license choice with the maintainer before adding (do not assume MIT by default — ask, or leave a `TODO` placeholder if this build plan is being run non-interactively).
- [ ] **P10-T3: Build + local install smoke test.** `python -m build` produces a wheel + sdist; `pip install dist/*.whl` into a clean venv and re-run the quickstart from P9-T3 against the installed package (not the editable source tree) to catch packaging bugs (missing files, bad `MANIFEST`, etc.). Confirm `examples/worker_recovery/validator_gateway.json` and `docs/schemas/policy.schema.json` are included if the package ships example/schema data — otherwise confirm they're deliberately excluded from the wheel.
- [ ] **P10-T4: Publish workflow (do not run automatically).** Add `.github/workflows/publish.yml` triggered on GitHub Release, using `pypa/gh-action-pypi-publish` with trusted publishing (OIDC) rather than a stored token. Leave it unexecuted until the maintainer explicitly cuts a release.

**Acceptance:** Fresh clean-room install from the built wheel works identically to the editable install used throughout development.

---

## Phase 11 — CLI Scaffolding Tool

Design goal: a developer should be able to run one command in a fresh project and get idempotent, importable starter files for controllers and gateways, without hand-copying from `examples/`.

- [ ] **P11-T1: `validator-gateway` console script**
  **Do:** Add a `src/validator_gateway/cli.py` module built on stdlib `argparse` (no new runtime dependency — keeps the framework-agnostic-core guarantee from Design Decision 4 intact) exposing a `main(argv: list[str] | None = None) -> int` entry point, and register it in `pyproject.toml`:
  ```toml
  [project.scripts]
  validator-gateway = "validator_gateway.cli:main"
  ```
  **File(s):** `src/validator_gateway/cli.py`, `pyproject.toml`
  **Acceptance:** After `pip install -e .`, `validator-gateway --help` runs and lists the `init` subcommand.

- [ ] **P11-T2: `validator-gateway init` command**
  **Do:** Implement `init` with signature `validator-gateway init [--path PATH] [--force]` (`PATH` defaults to cwd) that creates, relative to `PATH`:
  ```
  controllers/
    __init__.py
    example_controller.py   # subclasses BaseController; one async method raising NotFoundError as a template
  validator_gateways/
    __init__.py
    example_gateway.py       # constructs a ValidatorGateway around ExampleController, wired with default_logging_hook()
  ```
  Directory and file names are fixed (`controllers/`, `validator_gateways/`) to match the naming used elsewhere in this build plan and the docs — not developer-configurable in this phase.
  **File(s):** `src/validator_gateway/cli.py`, template content either as inline strings or `src/validator_gateway/_templates/*.py.tmpl`
  **Acceptance:** Running `validator-gateway init` in an empty directory creates exactly the four files above; the generated `example_controller.py` and `example_gateway.py` import cleanly and `python -c "from validator_gateways.example_gateway import gateway"` succeeds with no edits required.

- [ ] **P11-T3: Idempotency and `--force` safety**
  **Do:** Running `init` a second time without `--force` must not overwrite any existing file — it must report which files already exist and exit non-zero, rather than clobbering developer edits. `--force` overwrites unconditionally.
  **File(s):** `src/validator_gateway/cli.py`
  **Acceptance:** Test: run `init`, hand-edit `example_controller.py`, run `init` again without `--force` — file is untouched; run with `--force` — file is regenerated from the template.

- [ ] **P11-T4: CLI tests**
  **Do:** `tests/test_cli.py` invoking `cli.main([...])` against a `tmp_path`, covering: fresh `init`, `init` into a non-empty directory without `--force`, `init --force`, and `init --path <other-dir>`.
  **File(s):** `tests/test_cli.py`
  **Acceptance:** All four scenarios pass; no test writes outside `tmp_path`.

- [ ] **P11-T5: Document it**
  **Do:** Add a "Scaffolding a new project" section to `docs/quickstart.md` showing `pip install validator_gateway`, `validator-gateway init`, then wiring the generated gateway into a route.
  **File(s):** `docs/quickstart.md`
  **Acceptance:** Section present and matches the actual CLI output/behavior from P11-T2/T3.

---

## Phase 12 — FastAPI Demo Projects & Integration Testing

Phase 9's `examples/` prove the package *can* be wired up; this phase proves it stays wired up — each demo project gets its own real test suite, run in CI, so a regression in the core package is caught against realistic FastAPI usage, not just unit tests against the package in isolation.

- [ ] **P12-T1: Test `examples/fastapi_basic` end-to-end**
  **Do:** Add `examples/fastapi_basic/tests/test_api.py` using `fastapi.testclient.TestClient` against the example app itself (not a synthetic test app). Cover: the success path for each CRUD operation, and one HTTP request per `DomainError` subclass raised by the example's controller, asserting both the HTTP status (via P1-T3's mapping) and the `ErrorResponse` JSON shape.
  **File(s):** `examples/fastapi_basic/tests/test_api.py`
  **Acceptance:** `pytest examples/fastapi_basic` passes standalone (only requires the `[fastapi]` extra, not `[dev]`).

- [ ] **P12-T2: New demo — `examples/fastapi_scaffolded/`**
  **Do:** A demo project built by actually running `validator-gateway init` (Phase 11) inside `examples/fastapi_scaffolded/`, then filling in the generated `controllers/` and `validator_gateways/` stubs with a minimal real resource and a thin FastAPI route on top. Add its own `tests/test_api.py`. This is the proof that the CLI's output is usable, not just importable.
  **File(s):** `examples/fastapi_scaffolded/` (generated + hand-completed), `examples/fastapi_scaffolded/tests/test_api.py`
  **Acceptance:** Regenerating the scaffold (`validator-gateway init --force`) followed by re-applying the same hand-written glue reproduces an app that passes the same tests — proves the generated files aren't hand-patched out-of-band.

- [ ] **P12-T3: New demo — `examples/fastapi_recovery/`**
  **Do:** A FastAPI app where at least one route's gateway has a `RecoveryEngine` attached (deliberately deviating from Design Decision 8's usual REST-is-fail-fast default, to demonstrate it's possible when a developer wants retry-behind-a-slow-endpoint, per Phase 6's `get_gateway_factory` docstring). Bundle a `validator_gateway.json` exercising retry, redirect, and queue. Add tests asserting: a transient failure recovers via retry and the client still gets a 200, and a queued failure returns a distinct "accepted" response shape rather than hanging the request.
  **File(s):** `examples/fastapi_recovery/`, `examples/fastapi_recovery/validator_gateway.json`, `examples/fastapi_recovery/tests/test_api.py`
  **Acceptance:** Tests pass; a second small test wraps the same controller in a fail-fast gateway with no `recovery=` and shows the raw error surfacing instead — reinforcing Design Decision 8's "same controller, two gateways" guarantee end-to-end over real HTTP.

- [ ] **P12-T4: Wire demo tests into CI**
  **Do:** Extend `.github/workflows/ci.yml` (P0-T4) with a step (or separate job) that installs `.[fastapi,dev]` and runs `pytest examples/ -v` across all demo projects, so they run on every push/PR and can't silently rot independently of the core `tests/` suite.
  **File(s):** `.github/workflows/ci.yml`
  **Acceptance:** Deliberately breaking one demo (e.g. removing a required field from a generated stub) fails CI at the `examples/` step; fixing it passes again.

---

## Definition of Done (whole package)

- [ ] All phases 0–12 checked off.
- [ ] `pytest --cov` ≥ 90%, CI green on all three supported Python versions.
- [ ] `ruff check .` and `mypy src/` both pass with zero errors.
- [ ] `examples/fastapi_basic` runs standalone and demonstrates: success response, at least 3 distinct `DomainError` → formatted error mappings, one custom developer-defined exception registered via P1-T4, and the exception-logging hook firing (visible in console output).
- [ ] `examples/worker_recovery` runs standalone (no FastAPI installed required) and demonstrates the same controller/exception hierarchy recovering via retry, redirect, and queue steps driven entirely by `validator_gateway.json`, with zero REST/HTTP code involved anywhere in the call path.
- [ ] `validator-gateway init` (Phase 11) produces working, importable `controllers/` and `validator_gateways/` stubs in a scratch directory with no manual fixes required.
- [ ] `examples/fastapi_basic`, `examples/fastapi_scaffolded`, and `examples/fastapi_recovery` (Phase 12) each carry their own passing `tests/` suite, wired into CI independently of the core package's own test suite.
- [ ] README + docs allow a new developer to be productive with zero additional context, per Phase 9's acceptance criterion.
