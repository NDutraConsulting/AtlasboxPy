"""ShardRouter routes a key to one of N connection targets — hash-based
by default. A single-database deployment isn't a special "unsharded"
case with its own type to keep in sync with this one as real sharding
gets added later: it's just a `ShardRouter` with exactly one shard,
where every key routes to that same shard regardless of its value. That
means going from one database to N is a config change (add shards to the
router) — not a migration from one type to a different one.

Generic over the shard type (`T`) so the same router works for a
`DBQuantum` (this package), a Cassandra/Mongo connection config, or
anything else a caller wants to shard by key — `ShardRouter` itself has
no idea what a "database" is; it only knows how to pick one of N values.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Generic, TypeVar

T = TypeVar("T")


class ShardRouter(Generic[T]):
    def __init__(self, name: str, shards: Sequence[T]) -> None:
        if not shards:
            raise ValueError(f"ShardRouter(name={name!r}) needs at least one shard")
        self.name = name
        self._shards = tuple(shards)

    def shard_for(self, key: str) -> T:
        """Which shard a given key routes to. For a single-shard router,
        every key (including the empty string a caller with nothing to
        shard by can pass) routes to that one shard — sharding is opt-in
        by adding shards, not something every caller has to reason about
        up front."""
        return self._shards[self._bucket(key)]

    def _bucket(self, key: str) -> int:
        # A stable hash across runs and processes — unlike Python's
        # built-in hash(), which is randomized per-process
        # (PYTHONHASHSEED) specifically so it's *not* safe for anything
        # that needs the same key to always land on the same shard.
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % len(self._shards)

    @property
    def shard_count(self) -> int:
        return len(self._shards)

    def all_shards(self) -> tuple[T, ...]:
        return self._shards
