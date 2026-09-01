import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool, StaticPool

from atlasboxpy_db import (
    DBDriver,
    DBEnv,
    DBQuantum,
    DBQuantumRegistry,
    ShardRouter,
    StorageConflict,
    StorageTimeout,
    StorageUnavailable,
    session_scope,
)


def _in_memory_quantum(name: str) -> DBQuantum:
    return DBQuantum(
        name=name, driver=DBDriver.SQLITE, env=DBEnv.LOCAL, local_url="sqlite+aiosqlite:///:memory:"
    )


async def test_sessions_resolves_and_caches_an_engine_for_a_single_shard_router():
    registry = DBQuantumRegistry()
    router = ShardRouter(name="kanban", shards=[_in_memory_quantum("kanban")])

    sessions = registry.sessions(router)
    async with sessions() as session:
        result = await session.execute(text("select 1"))
        assert result.scalar_one() == 1

    # A second call for the same router/shard reuses the cached opener —
    # not a new engine/pool each time.
    assert registry.sessions(router) is sessions


async def test_register_sessions_preseeds_and_bypasses_url_resolution():
    registry = DBQuantumRegistry()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    preseeded = async_sessionmaker(engine, expire_on_commit=False)
    registry.register_sessions("kanban", preseeded)

    # A quantum whose local_url would fail to resolve (env misconfigured)
    # never gets asked to resolve it, because "kanban" was pre-seeded.
    broken_quantum = DBQuantum(
        name="kanban", driver=DBDriver.SQLITE, env=DBEnv.REMOTE, local_url=""
    )
    router = ShardRouter(name="kanban", shards=[broken_quantum])

    sessions = registry.sessions(router)
    assert sessions is preseeded
    await engine.dispose()


async def test_engine_for_rejects_a_url_that_does_not_match_the_declared_driver():
    registry = DBQuantumRegistry()
    mismatched = DBQuantum(
        name="mismatched", driver=DBDriver.POSTGRESQL, env=DBEnv.LOCAL,
        local_url="sqlite+aiosqlite:///:memory:",
    )
    router = ShardRouter(name="mismatched", shards=[mismatched])

    with pytest.raises(ValueError, match="doesn't start with 'postgresql'"):
        registry.sessions(router)


async def test_session_scope_commits_on_clean_exit():
    registry = DBQuantumRegistry()
    router = ShardRouter(name="kanban", shards=[_in_memory_quantum("kanban-commit")])
    sessions = registry.sessions(router)

    async with session_scope(sessions) as session:
        await session.execute(text("create table t (id integer)"))
        await session.execute(text("insert into t values (1)"))

    async with session_scope(sessions) as session:
        result = await session.execute(text("select count(*) from t"))
        assert result.scalar_one() == 1


async def test_session_scope_translates_operational_error_to_storage_unavailable():
    broken_engine = create_async_engine(
        "sqlite+aiosqlite:////nonexistent-directory-for-test/x.db"
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    broken_sessions = async_sessionmaker(broken_engine, expire_on_commit=False)

    with pytest.raises(StorageUnavailable):
        async with session_scope(broken_sessions) as session:
            await session.execute(text("select 1"))
    await broken_engine.dispose()


async def test_session_scope_translates_pool_timeout_to_storage_timeout():
    broken_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.05,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    broken_sessions = async_sessionmaker(broken_engine, expire_on_commit=False)
    held_connection = await broken_engine.connect()  # permanently checks out the only slot

    with pytest.raises(StorageTimeout):
        async with session_scope(broken_sessions) as session:
            await session.execute(text("select 1"))

    await held_connection.close()
    await broken_engine.dispose()


async def test_session_scope_translates_integrity_error_to_storage_conflict():
    registry = DBQuantumRegistry()
    router = ShardRouter(name="kanban", shards=[_in_memory_quantum("kanban-conflict")])
    sessions = registry.sessions(router)

    async with session_scope(sessions) as session:
        await session.execute(text("create table t (id integer primary key)"))
        await session.execute(text("insert into t values (1)"))

    with pytest.raises(StorageConflict):
        async with session_scope(sessions) as session:
            await session.execute(text("insert into t values (1)"))  # duplicate primary key
