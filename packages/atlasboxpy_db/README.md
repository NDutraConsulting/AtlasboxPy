# atlasboxpy-db

`DBQuantum` + `ShardRouter`: a connection-config base class for
SQLAlchemy where a single physical database isn't a special case with
its own type — it's just a `ShardRouter` with one shard. Going from one
database to many later is a config change (add shards), not a migration
from an "unsharded" type to a "sharded" one.

## Install

> **This is a prototype/example project — it is not published to PyPI and there's no plan to.** The `pip install` commands below are illustrative only; install from a local clone with `pip install -e .` to actually use it.

```bash
pip install atlasboxpy-db
```

## Usage

Declare one `DBQuantum` per physical database, wrap it in a `ShardRouter`
(one shard today, more later if you ever actually need them), and ask a
`DBQuantumRegistry` for a session opener:

```python
from atlasboxpy_db import DBDriver, DBEnv, DBQuantum, DBQuantumRegistry, ShardRouter, session_scope

# --- one physical database, declared once ---
KANBAN_DB_QUANTUM = ShardRouter(
    name="kanban",
    shards=[DBQuantum(name="kanban", driver=DBDriver.SQLITE, env=DBEnv.LOCAL, local_url="sqlite+aiosqlite:///kanban.db")],
)

# --- resolving a session ---
registry = DBQuantumRegistry()
sessions = registry.sessions(KANBAN_DB_QUANTUM)  # no shard key needed — one shard, every key routes to it

async with session_scope(sessions) as session:
    ...
```

Sharded, once you actually need it — the only thing that changes is the
router's declaration and the key you route by; every existing caller of
`registry.sessions(router, shard_key=...)` and `session_scope` is
unaffected:

```python
BOARD_DB_QUANTUM = ShardRouter(
    name="board",
    shards=[
        DBQuantum(name="board-0", driver=DBDriver.POSTGRESQL, env=DBEnv.REMOTE, local_url="", remote_url_env_var="BOARD_SHARD_0_URL"),
        DBQuantum(name="board-1", driver=DBDriver.POSTGRESQL, env=DBEnv.REMOTE, local_url="", remote_url_env_var="BOARD_SHARD_1_URL"),
    ],
)

sessions = registry.sessions(BOARD_DB_QUANTUM, shard_key=board_id)
```

Picking between a small set of *semantically different* databases (not
shards of the same one) — a shadow database seeded with test data for
post-deploy validation, say — is `VariantRouter`, not `ShardRouter`: it
never buckets or hashes, so an unrecognized or malformed label can never
land anywhere but the safe default:

```python
from atlasboxpy_db import VariantRouter

KANBAN_ENVIRONMENTS = VariantRouter(
    name="kanban",
    default=KANBAN_DB_QUANTUM,          # the ShardRouter declared above
    variants={"shadow": KANBAN_SHADOW_DB_QUANTUM},
)

# label is untrusted input end to end — e.g. a REST header, resolved by
# atlasboxpy_api's request-context middleware — never a value the caller
# constructed itself.
router = KANBAN_ENVIRONMENTS.resolve(label)
sessions = registry.sessions(router)
```

## What this package does and doesn't do

- **Does:** resolve a `DBQuantum` (or, via `ShardRouter`, one of several)
  into a cached, pooled `async_sessionmaker`; validate that a resolved
  URL actually matches its declared `DBDriver`; translate SQLAlchemy's
  own exceptions (`OperationalError`, pool `TimeoutError`, `IntegrityError`)
  into backend-neutral ones (`StorageUnavailable`, `StorageTimeout`,
  `StorageConflict`) so a caller doesn't need to know which driver is
  configured to react correctly to a failure.
- **Doesn't:** define your tables, write your queries, or own your
  cache — see `atlasboxpy_repository` for the caching side of a
  repository, and your own ORM models for the schema/query side.
  `DBQuantumRegistry` only ever hands back a session opener; what you do
  with it is yours.
- **Doesn't (yet):** cover non-SQL backends. `ShardRouter` is generic —
  nothing stops you from wrapping a Cassandra or Mongo connection config
  in one instead of a `DBQuantum` — but `DBQuantumRegistry`/
  `session_scope` are SQLAlchemy-specific; a non-SQL backend needs its
  own registry-equivalent.

## Documentation

- [`docs/decisions.md`](docs/decisions.md) — ADRs for the non-obvious
  choices (ShardRouter as the base case instead of a bolted-on
  "sharded" variant, a stable hash instead of Python's built-in `hash()`,
  the registry being constructed fresh per app instance rather than a
  module-level singleton, VariantRouter as a separate type from
  ShardRouter for exact-match environment selection), each with
  alternatives considered and
  performance/portability/debuggability/evolvability trade-offs.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
