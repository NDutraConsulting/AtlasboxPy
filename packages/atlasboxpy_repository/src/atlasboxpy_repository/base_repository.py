"""BaseRepository — a pluggable, read-through cache any repository can opt
into by subclassing it, instead of hand-rolling its own cache plumbing.
This module owns the *mechanism* (the backend implementations below);
which one actually gets used is configured per-repository, as
`cache_driver`/`cache_env` constants at the top of the concrete
repository's own file (see this package's README for a worked example)
and passed to `super().__init__(cache_driver=..., cache_env=...)` — not
hardcoded here, so two different repositories in the same app could each
pick their own cache technology.

    CacheDriver — which technology implements the cache:
        BARE_METAL: a plain in-memory dict. No external process, no
            network calls, nothing to configure. The default, and the
            only sane choice for local development without a running
            Redis.
        REDIS: a real Redis-backed cache, via redis.asyncio.

    CacheEnv — which Redis deployment to talk to (only consulted when
        cache_driver is REDIS; ignored for BARE_METAL):
        LOCAL: localhost:6379 — a Redis you're running yourself (e.g.
            `docker run -p 6379:6379 redis`).
        REMOTE: a managed/hosted Redis reached via the REDIS_URL
            environment variable.

Both are real Enums, not bare strings — assigning `cache_driver = "redis"`
(a typo-prone string) is a type error the moment a type checker looks at
it, not a `ValueError` discovered at runtime the first time the wrong
branch is hit.

A subclass never sees any of this beyond its own two constants — it just
calls `await self.cache.get(key)` / `.set(key, value)` / `.invalidate(key)`
and builds whatever keys make sense for its own data. Flipping a
repository's cache_driver from BARE_METAL to REDIS changes nothing about
how it calls the cache; only what happens underneath.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class CacheDriver(str, Enum):
    """A str subclass, not just an Enum — so it reads as "bare_metal", not
    "CacheDriver.BARE_METAL" or an opaque int, wherever it lands in a log
    line or an f-string."""

    BARE_METAL = "bare_metal"
    REDIS = "redis"

    def __str__(self) -> str:
        return self.value


class CacheEnv(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"

    def __str__(self) -> str:
        return self.value


class CacheBackend(ABC):
    """What every cache driver implements — get/set/invalidate by a plain
    string key. Values must be JSON-serializable: a real network backend
    like Redis has to serialize anyway, so the in-memory one is held to
    the same contract rather than silently allowing something a driver
    swap would later break on."""

    @abstractmethod
    async def get(self, key: str) -> Any: ...

    @abstractmethod
    async def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    async def invalidate(self, key: str) -> None: ...


class BareMetalCacheBackend(CacheBackend):
    """A plain in-memory dict — one process, no external dependency, gone
    the moment the process restarts. Every method is synchronous
    underneath but still declared async, so a subclass's call sites don't
    need to change when cache_driver flips to "redis"."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    async def invalidate(self, key: str) -> None:
        self._store.pop(key, None)


class RedisCacheBackend(CacheBackend):
    """A real Redis-backed cache via redis.asyncio (pip install
    "redis>=5.0" — ships redis.asyncio, no separate aioredis package
    needed). Values are JSON-encoded, since Redis itself only stores
    bytes/strings."""

    _TTL_SECONDS = 300  # unlike the dict backend, a network cache needs a
    # bound: without one, a key invalidated by something other than this
    # app (a direct DB write, a different service instance) would stay
    # cached forever.

    def __init__(self, env: CacheEnv) -> None:
        from redis.asyncio import Redis  # only imported when this driver is actually selected

        if env is CacheEnv.LOCAL:
            self._redis = Redis(host="localhost", port=6379)
        else:
            self._redis = Redis.from_url(os.environ["REDIS_URL"])

    async def get(self, key: str) -> Any:
        raw = await self._redis.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any) -> None:
        await self._redis.set(key, json.dumps(value), ex=self._TTL_SECONDS)

    async def invalidate(self, key: str) -> None:
        await self._redis.delete(key)


def _build_cache_backend(driver: CacheDriver, env: CacheEnv) -> CacheBackend:
    if driver is CacheDriver.REDIS:
        return RedisCacheBackend(env)
    return BareMetalCacheBackend()


class BaseRepository:
    """Subclass this and call `super().__init__(cache_driver=..., cache_env=...)`
    to get a pluggable cache at self.cache — see the module docstring for
    what each option means, and the concrete subclass's own file for which
    ones it actually picked."""

    def __init__(
        self,
        *,
        cache_driver: CacheDriver = CacheDriver.BARE_METAL,
        cache_env: CacheEnv = CacheEnv.LOCAL,
    ) -> None:
        self.cache: CacheBackend = _build_cache_backend(cache_driver, cache_env)
