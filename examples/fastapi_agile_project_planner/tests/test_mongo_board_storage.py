"""MongoBoardStorage always refuses to construct — see its module
docstring for why this is a deliberate rejection, not an unfinished
implementation."""

import pytest
from atlasboxpy_db import UnsupportedBackendError

from examples.fastapi_agile_project_planner.app.backend.infrastructure.database.db_connections.mongo_quantum import (
    MongoQuantum,
)
from examples.fastapi_agile_project_planner.app.backend.infrastructure.database.orm_models.mongo_board_orm_model import (
    MONGODB_REJECTED_REASON,
    MongoBoardStorage,
)


def test_mongo_board_storage_refuses_to_construct():
    with pytest.raises(UnsupportedBackendError):
        MongoBoardStorage(MongoQuantum(uri="mongodb://localhost", database="kanban"))


def test_mongo_board_storage_exception_carries_the_rejection_reason():
    with pytest.raises(UnsupportedBackendError) as excinfo:
        MongoBoardStorage(MongoQuantum(uri="mongodb://localhost", database="kanban"))
    assert str(excinfo.value) == MONGODB_REJECTED_REASON
    assert "2024" in str(excinfo.value)
    assert "pgvector" in str(excinfo.value)
