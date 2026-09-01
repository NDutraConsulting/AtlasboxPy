"""CardActivityLog's connection config — deliberately not a `DBQuantum`
(atlasboxpy_db): Cassandra doesn't speak SQLAlchemy's engine/session
model, so it gets its own tiny config type instead of being forced under
DBQuantum's SQL-dialect assumptions, per the Entity-Type Storage spec's
own rule that a non-SQL backend "receives its own backend configuration
type"."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CassandraQuantum:
    keyspace: str
    contact_points: tuple[str, ...] = ("127.0.0.1",)


CARD_ACTIVITY_LOG_QUANTUM = CassandraQuantum(keyspace="kanban")
