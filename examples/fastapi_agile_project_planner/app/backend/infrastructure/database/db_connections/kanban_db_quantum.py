"""The single connection `boards`, `columns`, and `cards` all share —
one physical SQLite database, wrapped as a one-shard `ShardRouter`
(atlasboxpy_db). db_connections/ defines a connection per physical
database, not per table: board/column/card were never really independent
(see kanban_service.py's docstring), so they were never going to get
separate connections in practice.

Wrapping even this single database in a `ShardRouter` — rather than a
bare `DBQuantum` — means going from one database to many later (see
`ShardRouter`'s own docstring in atlasboxpy_db) is a config change here,
not a migration to a different type every caller has to be updated for.
Every current caller of `registry.sessions(KANBAN_DB_QUANTUM)` needs no
shard key: a one-shard router routes every key to that same shard.

`card_activity_log_quantum.py` gets its own file precisely because it
*is* a genuinely different physical database — a Cassandra cluster, not
this SQLite file (and not SQLAlchemy-based, so not a `DBQuantum`/
`ShardRouter` case at all — see that module). If `cards` is ever
actually split onto its own instance (see docs/decisions.md's ADR-1 on
why that's a real, deliberate trade-off, not a free one), that's the
moment to add a second shard to this router (or a card-specific one) and
repoint `card_orm_model.py`'s caller — not before.
"""

from __future__ import annotations

from atlasboxpy_db import DBDriver, DBEnv, DBQuantum, ShardRouter

# Change this — not anything in orm_models/ — to move the whole kanban
# aggregate (all three tables) onto a different database instance or SQL
# dialect. A Postgres example (never exercised in this demo — asyncpg
# isn't a dependency) would look like:
#   KANBAN_DB_QUANTUM = ShardRouter(
#       name="kanban",
#       shards=[DBQuantum(
#           name="kanban", driver=DBDriver.POSTGRESQL, env=DBEnv.REMOTE,
#           local_url="", remote_url_env_var="KANBAN_DATABASE_URL",
#       )],
#   )
KANBAN_DB_QUANTUM = ShardRouter(
    name="kanban",
    shards=[DBQuantum(name="kanban", driver=DBDriver.SQLITE, env=DBEnv.LOCAL, local_url="")],
)
