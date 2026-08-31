# atlasboxpy-repository

A `BaseRepository` class with a pluggable, read-through cache — swap
between a plain in-memory dict and Redis by changing two config constants,
with no changes anywhere else in your repository subclass.

## Install

> **This is a prototype/example project — it is not published to PyPI and there's no plan to.** The `pip install` commands below are illustrative only; install from a local clone with `pip install -e .` to actually use it.

```bash
pip install atlasboxpy-repository
# or, if you want the Redis driver available:
pip install "atlasboxpy-repository[redis]"
```

## Usage

Subclass `BaseRepository`, declare your own cache config at the top of
your file, and call `super().__init__(cache_driver=..., cache_env=...)`:

```python
from atlasboxpy_repository import BaseRepository, CacheDriver, CacheEnv

# --- cache configuration for this repository ---
cache_driver: CacheDriver = CacheDriver.BARE_METAL
cache_env: CacheEnv = CacheEnv.LOCAL
# -------------------------------------------------


class UserRepository(BaseRepository):
    def __init__(self, session_factory) -> None:
        super().__init__(cache_driver=cache_driver, cache_env=cache_env)
        self._session_factory = session_factory

    @staticmethod
    def _cache_key(user_id: str) -> str:
        return f"user:{user_id}"

    async def get_user(self, user_id: str) -> dict | None:
        cached = await self.cache.get(self._cache_key(user_id))
        if cached is not None:
            return cached
        data = await self._fetch_from_db(user_id)
        if data is not None:
            await self.cache.set(self._cache_key(user_id), data)
        return data

    async def update_user(self, user_id: str, **fields) -> None:
        await self._write_to_db(user_id, **fields)
        await self.cache.invalidate(self._cache_key(user_id))
```

Flipping `cache_driver` to `CacheDriver.REDIS` (and `cache_env` to
`CacheEnv.LOCAL` for a `localhost:6379` Redis, or `CacheEnv.REMOTE` for a
managed one reached via the `REDIS_URL` environment variable) changes
nothing about how `UserRepository` calls `self.cache` — only what happens
underneath.

## Why a base class instead of a decorator or a standalone cache client

The cache decision (which technology, TTLs, key format) belongs to
whoever owns the data access layer for a given entity — one repository in
your app might reasonably want Redis while another is fine with an
in-memory dict. `BaseRepository` makes that a two-line decision at the top
of each repository's own file, not a global, app-wide cache client every
repository has to agree on.

See `atlasboxpy_repository.base_repository` for the full implementation —
it's under 130 lines, including docstrings.

## License

Apache License 2.0 — see `LICENSE` and `NOTICE`.
