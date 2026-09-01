"""Exercises CassandraCardActivityLogStorage's connection setup, CQL, and
entity mapping without a real Cassandra cluster or the cassandra-driver
dependency installed — stubs `cassandra.cluster` in sys.modules before
the storage class's lazy `from cassandra.cluster import Cluster` import
runs, the standard technique for testing code behind an optional,
lazily-imported dependency (see also RedisCacheBackend in
atlasboxpy_repository, which the same technique would apply to)."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from examples.fastapi_kanban.app.backend.infrastructure.database.db_connections.card_activity_log_quantum import (
    CassandraQuantum,
)
from examples.fastapi_kanban.app.backend.infrastructure.database.orm_models.card_activity_log_orm_model import (
    CassandraCardActivityLogStorage,
)


class _FakeRow:
    def __init__(self, id, card_id, board_id, action, logged_at):
        self.id = id
        self.card_id = card_id
        self.board_id = board_id
        self.action = action
        self.logged_at = logged_at


@pytest.fixture
def fake_cluster(monkeypatch):
    """Installs a fake `cassandra`/`cassandra.cluster` module pair into
    sys.modules — present before the storage class's lazy import runs, so
    it resolves to these mocks instead of ModuleNotFoundError. Returns
    (fake_session, fake_cluster_cls) so tests can assert on calls made
    through them."""
    fake_session = MagicMock(name="session")
    fake_cluster_instance = MagicMock(name="cluster_instance")
    fake_cluster_instance.connect.return_value = fake_session
    fake_cluster_cls = MagicMock(name="Cluster", return_value=fake_cluster_instance)

    fake_cassandra_pkg = types.ModuleType("cassandra")
    fake_cluster_module = types.ModuleType("cassandra.cluster")
    fake_cluster_module.Cluster = fake_cluster_cls

    monkeypatch.setitem(sys.modules, "cassandra", fake_cassandra_pkg)
    monkeypatch.setitem(sys.modules, "cassandra.cluster", fake_cluster_module)
    return fake_session, fake_cluster_cls


def test_construction_connects_sets_keyspace_and_creates_the_table(fake_cluster):
    fake_session, fake_cluster_cls = fake_cluster

    CassandraCardActivityLogStorage(CassandraQuantum(keyspace="kanban_test"))

    fake_cluster_cls.assert_called_once_with(["127.0.0.1"])
    fake_session.set_keyspace.assert_called_once_with("kanban_test")
    create_table_calls = [
        call for call in fake_session.execute.call_args_list if "CREATE TABLE" in call.args[0]
    ]
    assert len(create_table_calls) == 1
    assert "PRIMARY KEY (card_id, logged_at)" in create_table_calls[0].args[0]
    assert "CLUSTERING ORDER BY (logged_at DESC)" in create_table_calls[0].args[0]


async def test_append_inserts_with_card_id_as_partition_key(fake_cluster):
    fake_session, _ = fake_cluster
    storage = CassandraCardActivityLogStorage(CassandraQuantum(keyspace="kanban_test"))
    fake_session.execute.reset_mock()

    result = await storage.append(card_id="card-1", board_id="board-1", action="moved")

    fake_session.execute.assert_called_once()
    cql, params = fake_session.execute.call_args.args
    assert "INSERT INTO card_activity_log" in cql
    card_id, logged_at, log_id, board_id, action = params
    assert card_id == "card-1"
    assert board_id == "board-1"
    assert action == "moved"
    assert isinstance(logged_at, datetime)
    assert result.card_id == "card-1"
    assert result.board_id == "board-1"
    assert result.action == "moved"
    assert result.id == str(log_id)


async def test_list_for_card_queries_by_partition_key_and_maps_rows(fake_cluster):
    fake_session, _ = fake_cluster
    storage = CassandraCardActivityLogStorage(CassandraQuantum(keyspace="kanban_test"))
    now = datetime.now(timezone.utc)
    fake_session.execute.return_value = [
        _FakeRow(id="11111111-1111-1111-1111-111111111111", card_id="card-1",
                  board_id="board-1", action="created", logged_at=now),
    ]

    results = await storage.list_for_card("card-1", limit=10)

    cql, params = fake_session.execute.call_args.args
    assert "WHERE card_id = %s" in cql
    assert params == ("card-1", 10)
    assert len(results) == 1
    assert results[0].card_id == "card-1"
    assert results[0].action == "created"
    assert results[0].logged_at == now.isoformat()
