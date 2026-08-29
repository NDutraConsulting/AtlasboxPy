# Recovery policies

`validator_gateway.json` is what lets a worker or agent call `gateway.handle()`
directly and get automatic retry, fallback, or queue-based recovery — without
any REST layer involved, and without changing how a fail-fast REST gateway
wrapping the *same controller* behaves. It reuses `DomainError.code` as the
only dispatch key; there's no second taxonomy to keep in sync.

## Shape

A policy file maps a code to an ordered list of steps:

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

A JSON Schema for editor/CI validation lives at
[`docs/schemas/policy.schema.json`](schemas/policy.schema.json).

Load it with `JSONFilePolicyStore`:

```python
from validator_gateway.recovery import JSONFilePolicyStore, RecoveryEngine

engine = RecoveryEngine(policy_store=JSONFilePolicyStore("validator_gateway.json"))
gateway = ValidatorGateway(controller=UserController(user_service), recovery=engine)
```

At load time, every top-level key is validated against `known_codes()` — a typo
like `"upstrem_error"` raises `PolicyValidationError` immediately, naming the bad
key, rather than silently never matching anything at runtime.

## The step vocabulary

Steps in the list for a code are tried **in order** until one succeeds — the
list *is* the workflow: `[RETRY, REDIRECT, QUEUE]` means "retry first, fall
back to the redirect target if retries are exhausted, hand off to a queue if
the redirect also fails."

| action     | spec           | behavior                                                                 |
|------------|----------------|---------------------------------------------------------------------------|
| `retry`    | `RetrySpec`    | Re-invokes the original controller call up to `max_attempts` times, with exponential backoff (`backoff_base_seconds * backoff_multiplier ** attempt`, optionally jittered). Moves to the next step if every attempt fails. |
| `redirect` | `RedirectSpec` | Calls the fallback registered under `target` via `gateway.register_fallback(name, target)`. Moves to the next step if the fallback itself raises a `DomainError`. |
| `queue`    | `QueueSpec`    | Builds a `QueuedJob` (controller class, method name, JSON-serializable `args`/`kwargs`, the original code, an attempt count) and hands it to your `EnqueueHook`. `handle()` returns `SuccessResponse(data=None)` — "accepted for later processing," not a synchronous result. |
| `fail`     | *(none)*       | Raises the original exception immediately — no more steps are tried.     |

A policy that exhausts every step without hitting `fail` re-raises the
original exception, which `handle()` then formats as the usual `ErrorResponse`
— a worker gateway degrades to exactly the REST gateway's behavior once
recovery genuinely can't help.

`max_total_steps` (default `10`, set on `RecoveryEngine(...)`) caps the total
number of steps executed across the whole chain, regardless of how many steps
a policy file lists — a guard against a pathological or hand-edited policy
causing runaway retries, independent of any individual step's own limits.

## The `retryable` flag

Every `DomainError` subclass carries a `retryable: bool` class attribute
(`PermissionDeniedError`, `UnauthenticatedError`, and `ValidationFailedError`
default to `False` — retrying without changing credentials or the input
cannot succeed; everything else defaults to `True`). `JSONFilePolicyStore`
rejects, at load time, any `retry` step configured against a code whose type
has `retryable = False`:

```json
{"permission_denied": [{"action": "retry"}]}
```

raises `PolicyValidationError` naming `permission_denied` — this is meant to
catch a misconfigured policy file before it ships, not to be worked around.
Use `{"action": "fail"}` (or `redirect`/`queue`) for non-retryable codes
instead.

## Redirect targets: the security rule

`RedirectSpec.target` is a **name**, never a dotted import path. It resolves
*only* through `gateway.register_fallback(name, target)`, called explicitly in
Python at gateway construction time:

```python
gateway.register_fallback("degraded_create_user", degraded_create_user_fn)
```

There is no `importlib`, no `eval`, and no `getattr` on a free string anywhere
in the redirect resolution path — a policy file is data, and data never names
arbitrary importable code. A `target` that was never registered raises
`UnregisteredFallbackError` with a clear message the moment the recovery
engine needs it — fail loud, not a silent fallthrough to `fail`.

## A worked example

See [`examples/worker_recovery/main.py`](../examples/worker_recovery/main.py) —
a standalone script (no FastAPI installed) that runs the exact policy file
above against a simulated flaky controller and prints which step resolved
each case: one where retry alone recovers, one where retries exhaust and a
redirect recovers, one where both exhaust and the call is queued, and one
where a `permission_denied` failure hits its `fail` step immediately with no
recovery attempted.

## Future: a database-backed policy store

`PolicyStore` (the `Protocol` `JSONFilePolicyStore` implements) is already a
sufficient seam for a database-backed store — implement a class with
`get_policy(code) -> list[RecoveryStep]` backed by whatever storage you like.
`DBPolicyStore` in `recovery/policy_store.py` documents the intended shape (a
table keyed by `code` storing a JSON blob of steps, validated on *write* with
the same rules `JSONFilePolicyStore` applies on read) without shipping a
concrete implementation.
