import pytest

from atlasboxpy_repository import BareMetalCacheBackend, BaseRepository, CacheDriver, CacheEnv


class InMemoryRepository(BaseRepository):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db: dict[str, str] = {}

    async def get_thing(self, thing_id: str) -> str | None:
        cached = await self.cache.get(thing_id)
        if cached is not None:
            return cached
        value = self.db.get(thing_id)
        if value is not None:
            await self.cache.set(thing_id, value)
        return value

    async def set_thing(self, thing_id: str, value: str) -> None:
        self.db[thing_id] = value
        await self.cache.invalidate(thing_id)


def test_defaults_to_bare_metal_driver():
    repo = InMemoryRepository()
    assert isinstance(repo.cache, BareMetalCacheBackend)


def test_cache_driver_and_cache_env_are_string_enums():
    assert CacheDriver.BARE_METAL == "bare_metal"
    assert CacheEnv.LOCAL == "local"
    assert str(CacheDriver.BARE_METAL) == "bare_metal"
    assert str(CacheEnv.REMOTE) == "remote"


@pytest.mark.asyncio
async def test_get_populates_cache_on_miss_then_hits_it():
    repo = InMemoryRepository()
    repo.db["1"] = "Ada"

    assert await repo.get_thing("1") == "Ada"
    assert await repo.cache.get("1") == "Ada"

    # Change the "database" directly, bypassing the repository — the next
    # read should still come from cache, proving it's actually a cache hit
    # and not just re-reading the db every time.
    repo.db["1"] = "Changed"
    assert await repo.get_thing("1") == "Ada"


@pytest.mark.asyncio
async def test_write_invalidates_the_cache():
    repo = InMemoryRepository()
    repo.db["1"] = "Ada"
    await repo.get_thing("1")  # populate the cache
    assert await repo.cache.get("1") == "Ada"

    await repo.set_thing("1", "Ada Lovelace")

    assert await repo.cache.get("1") is None
    assert await repo.get_thing("1") == "Ada Lovelace"


@pytest.mark.asyncio
async def test_cache_miss_for_unknown_key_returns_none():
    repo = InMemoryRepository()
    assert await repo.get_thing("missing") is None


def test_redis_driver_selected_without_redis_installed_fails_only_on_import():
    """Proves the driver selection itself works — RedisCacheBackend is
    actually constructed and only fails because the optional `redis`
    dependency isn't installed, not because of a logic error in
    _build_cache_backend."""
    try:
        import redis  # noqa: F401

        pytest.skip("redis is installed in this environment; nothing to prove here")
    except ImportError:
        pass

    with pytest.raises(ModuleNotFoundError):
        InMemoryRepository(cache_driver=CacheDriver.REDIS, cache_env=CacheEnv.LOCAL)
