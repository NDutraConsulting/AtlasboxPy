"""CassandraCardActivityLogStorage — illustrative, like this app's
Postgres/MySQL `DB_QUANTUM` examples elsewhere: `cassandra-driver` isn't a
dependency of this demo, and there's no cluster to run it against.
What's real and tested (see tests/test_cassandra_card_activity_log_storage.py,
which stubs the driver via sys.modules) is the CQL and the partition/
clustering-key modeling — exactly what you'd deploy if you added the
dependency and pointed it at a real cluster. `cassandra.cluster` is
imported lazily, inside __init__, the same way atlasboxpy_repository's
RedisCacheBackend lazily imports `redis.asyncio` — so this module stays
importable, and its query-building/entity-mapping logic stays testable,
without the package installed.

Why Cassandra for this entity specifically: an activity log is
append-only, queried almost exclusively "give me the last N events for
this one card, most recent first" — exactly Cassandra's wide-column
strength (one partition per card_id, clustered by logged_at DESC, no
cross-partition scan ever needed for the only query this entity actually
serves) and exactly the access pattern a relational secondary index
doesn't reward the way a partition key does at real log volume. See
docs/decisions.md for the ADR.

Not wired into KanbanService/KanbanController — no card mutation
actually calls `.append()` today. This demonstrates the storage-layer
pattern for a genuinely different backend; wiring it into the live
card-lifecycle flow is a separate feature, not part of this example.

CardActivityLog has no table in tables/ (it's not SQLAlchemy-backed) and
no DBQuantum in db_connections/ (see db_connections/card_activity_log_quantum.py
for its CassandraQuantum instead) — a non-SQL entity opts out of both,
not just one.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..db_connections.card_activity_log_quantum import CassandraQuantum
from ..entities import CardActivityLog

_CREATE_TABLE_CQL = """
CREATE TABLE IF NOT EXISTS card_activity_log (
    card_id text,
    logged_at timestamp,
    id uuid,
    board_id text,
    action text,
    PRIMARY KEY (card_id, logged_at)
) WITH CLUSTERING ORDER BY (logged_at DESC)
"""

_INSERT_CQL = """
INSERT INTO card_activity_log (card_id, logged_at, id, board_id, action)
VALUES (%s, %s, %s, %s, %s)
"""

_SELECT_CQL = """
SELECT id, card_id, board_id, action, logged_at
FROM card_activity_log
WHERE card_id = %s
LIMIT %s
"""


def _to_entity(row: Any) -> CardActivityLog:
    return CardActivityLog(
        id=str(row.id),
        card_id=row.card_id,
        board_id=row.board_id,
        action=row.action,
        logged_at=row.logged_at.isoformat(),
    )


class CassandraCardActivityLogStorage:
    """Owns the `card_activity_log` table — one partition per `card_id`,
    clustered by `logged_at` descending. Whatever would call this (a
    repository, if this were wired into a live feature) never sees a CQL
    string, a partition key, or a driver-specific row type — same
    boundary as every SQLAlchemy-backed orm_model in this app, just on a
    different backend."""

    def __init__(self, quantum: CassandraQuantum) -> None:
        # Lazy import — see module docstring. Not installed, so untyped.
        from cassandra.cluster import Cluster  # type: ignore[import-not-found]

        self._cluster = Cluster(list(quantum.contact_points))
        self._session = self._cluster.connect()
        self._session.set_keyspace(quantum.keyspace)
        self._session.execute(_CREATE_TABLE_CQL)

    async def append(self, card_id: str, board_id: str, action: str) -> CardActivityLog:
        log_id = uuid4()
        logged_at = datetime.now(timezone.utc)
        await asyncio.get_running_loop().run_in_executor(
            None,
            self._session.execute,
            _INSERT_CQL,
            (card_id, logged_at, log_id, board_id, action),
        )
        return CardActivityLog(
            id=str(log_id),
            card_id=card_id,
            board_id=board_id,
            action=action,
            logged_at=logged_at.isoformat(),
        )

    async def list_for_card(self, card_id: str, limit: int = 50) -> list[CardActivityLog]:
        rows = await asyncio.get_running_loop().run_in_executor(
            None, self._session.execute, _SELECT_CQL, (card_id, limit)
        )
        return [_to_entity(row) for row in rows]
