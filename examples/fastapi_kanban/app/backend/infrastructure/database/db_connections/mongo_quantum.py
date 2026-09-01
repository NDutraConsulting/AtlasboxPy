"""What a real Mongo-backed entity's connection config would have looked
like — kept only so its constructor signature matches what a real
implementation's would be. Raises immediately, same as
orm_models/mongo_board_orm_model.py's MongoBoardStorage: MongoDB was
evaluated and rejected on purpose here, not merely never built.

Full ADR (context, alternatives considered, consequences) is
docs/decisions.md, ADR-2."""

from __future__ import annotations

from atlasboxpy_db import UnsupportedBackendError

MONGODB_REJECTED_REASON = (
    "As of 2024 we no longer use MongoDB: Postgres provides better search "
    "and indexing performance with JSONB, letting you store unstructured "
    "data with better searchability and better tooling. MongoDB doesn't "
    "earn its keep in modern software environments once you have pgvector, "
    "JSONB, and Postgres's own partitioning tools available — a simple "
    "hash-based shard service gives you much better performance."
)


class MongoQuantum:
    def __init__(self, uri: str, database: str) -> None:
        raise UnsupportedBackendError(MONGODB_REJECTED_REASON)
