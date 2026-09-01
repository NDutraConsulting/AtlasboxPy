# atlasboxpy-api

`HeaderContextMiddleware` + `RequestContext`: a plain ASGI middleware
(no framework dependency — works with Starlette, FastAPI, or any ASGI
app unmodified) that reads one HTTP header, resolves it through a
function you supply, and makes the result available for exactly that
request's duration — never leaking into a concurrent request the way a
module-level global would.

The motivating case: routing a request to a shadow database seeded with
test data for post-deploy validation, selected by a header, without
risking that header ever silently pointing a request at production data.
This package only does "read a header safely, expose it request-scoped" —
composing that with something like `atlasboxpy_db`'s `VariantRouter` (an
exact-match, safe-by-default resolver) is your app's job at its own
composition root.

## Install

> **This is a prototype/example project — it is not published to PyPI and there's no plan to.** The `pip install` commands below are illustrative only; install from a local clone with `pip install -e .` to actually use it.

```bash
pip install atlasboxpy-api
```

## Usage

```python
from atlasboxpy_api import HeaderContextMiddleware, RequestContext
from atlasboxpy_db import VariantRouter
from starlette.applications import Starlette

# --- declared once, at your composition root ---
db_environment: RequestContext[str] = RequestContext("db-environment", default="prod")

KANBAN_ENVIRONMENTS = VariantRouter(
    name="kanban",
    default="prod",
    variants={"shadow": "shadow"},
)

app = Starlette(routes=[...])
app.add_middleware(
    HeaderContextMiddleware,
    header_name="X-DB-Environment",
    context=db_environment,
    resolve=KANBAN_ENVIRONMENTS.resolve,  # untrusted label in, safe default or exact match out
)

# --- anywhere downstream, for the duration of that one request ---
def build_kanban_storages():
    variant = db_environment.get()  # "prod" or "shadow" — never anything else
    ...
```

## What this package does and doesn't do

- **Does:** extract one HTTP header from an ASGI scope, hand its raw
  (untrusted) value to a function you supply, and expose whatever that
  function returns via a `RequestContext` for the lifetime of that one
  request — reset automatically once the request completes, even if a
  downstream handler raises.
- **Doesn't:** validate, allowlist, or interpret the header value itself
  — that's entirely `resolve`'s job. This package has no opinion about
  what a "valid" value looks like; pair it with something like
  `atlasboxpy_db`'s `VariantRouter`, whose `resolve()` is specifically
  built to fall back to a safe default for anything it doesn't
  recognize, rather than writing that logic ad hoc per app.
- **Doesn't:** depend on any specific web framework. `HeaderContextMiddleware`
  is a plain ASGI middleware (`__call__(self, scope, receive, send)`) —
  it happens to be usable via Starlette's/FastAPI's `add_middleware()`
  because both accept any ASGI-shaped middleware class, not because this
  package imports either of them.

## Documentation

- [`docs/decisions.md`](docs/decisions.md) — ADRs for the non-obvious
  choices (`ContextVar`-backed request scoping instead of a global,
  resolution logic living entirely outside this package), each with
  alternatives considered and
  performance/portability/debuggability/evolvability trade-offs.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
