import pytest

from atlasboxpy_db import DBDriver, DBEnv, DBQuantum


def test_local_quantum_resolves_its_local_url():
    quantum = DBQuantum(
        name="kanban", driver=DBDriver.SQLITE, env=DBEnv.LOCAL, local_url="sqlite+aiosqlite:///x.db"
    )
    assert quantum.resolve_url() == "sqlite+aiosqlite:///x.db"


def test_remote_quantum_resolves_from_its_env_var(monkeypatch):
    monkeypatch.setenv("KANBAN_DATABASE_URL", "postgresql+asyncpg://prod/kanban")
    quantum = DBQuantum(
        name="kanban",
        driver=DBDriver.POSTGRESQL,
        env=DBEnv.REMOTE,
        local_url="",
        remote_url_env_var="KANBAN_DATABASE_URL",
    )
    assert quantum.resolve_url() == "postgresql+asyncpg://prod/kanban"


def test_remote_quantum_without_env_var_name_raises_value_error():
    quantum = DBQuantum(name="kanban", driver=DBDriver.POSTGRESQL, env=DBEnv.REMOTE, local_url="")
    with pytest.raises(ValueError, match="remote_url_env_var"):
        quantum.resolve_url()


def test_remote_quantum_with_unset_env_var_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("KANBAN_DATABASE_URL", raising=False)
    quantum = DBQuantum(
        name="kanban",
        driver=DBDriver.POSTGRESQL,
        env=DBEnv.REMOTE,
        local_url="",
        remote_url_env_var="KANBAN_DATABASE_URL",
    )
    with pytest.raises(RuntimeError, match=r"\$KANBAN_DATABASE_URL"):
        quantum.resolve_url()


def test_drivers_and_envs_are_real_enums_not_bare_strings():
    assert str(DBDriver.SQLITE) == "sqlite"
    assert str(DBEnv.LOCAL) == "local"
    assert DBDriver.SQLITE == "sqlite"  # str subclass, compares equal to the raw value too
