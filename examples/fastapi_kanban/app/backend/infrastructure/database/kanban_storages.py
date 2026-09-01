"""Composition helpers: build each entity's own SQLAlchemy storage from
whatever DBQuantumRegistry main.py's create_app() most recently registered
as the default (see session.py's get_default_quantum_registry) — the same
shared-process-state pattern db_connections/db_simulation.py's
set_simulation()/get_simulation() already is. Each entity's own repository
(infrastructure/repositories/{board,column,card}_repository.py) calls its
own build_*_storage() here instead of constructing
SQLAlchemy{Board,Column,Card}Storage itself, so it never needs to know a
DBQuantumRegistry or DBQuantum exists — matching the rule that a
repository depends on what its own orm_model returns (Board/Column/Card —
see entities.py), not on how it gets a DBQuantum, engine, or session
factory. This is also the one place that resolves the kanban database's
quantum (db_connections/) and hands the matching sessions to each
orm_model (orm_models/) — everywhere else, those two only ever meet here.
All three storages share one quantum today, so all three builders below
resolve to the same cached session factory (DBQuantumRegistry caches by
quantum name) — building them independently costs nothing extra.
"""

from __future__ import annotations

from atlasboxpy_db import SessionOpener
from sqlalchemy.ext.asyncio import AsyncSession

from .db_connections.db_simulation import active_session_factory
from .db_connections.kanban_db_quantum import KANBAN_DB_QUANTUM
from .orm_models.board_orm_model import SQLAlchemyBoardStorage
from .orm_models.card_orm_model import SQLAlchemyCardStorage
from .orm_models.column_orm_model import SQLAlchemyColumnStorage
from .session import get_default_quantum_registry


def _with_simulation(real: SessionOpener) -> SessionOpener:
    """Re-checks db_simulation's "is the DB down right now?" flag on
    every call — the debug endpoint can toggle it mid-process, so this
    can't be resolved once when the registry hands out `real` and cached
    from then on, the way the underlying engine/pool is."""

    def opener() -> AsyncSession:
        return active_session_factory(real)()

    return opener


def _sessions() -> SessionOpener:
    registry = get_default_quantum_registry()
    return _with_simulation(registry.sessions(KANBAN_DB_QUANTUM))


def build_board_storage() -> SQLAlchemyBoardStorage:
    return SQLAlchemyBoardStorage(_sessions())


def build_column_storage() -> SQLAlchemyColumnStorage:
    return SQLAlchemyColumnStorage(_sessions())


def build_card_storage() -> SQLAlchemyCardStorage:
    return SQLAlchemyCardStorage(_sessions())
