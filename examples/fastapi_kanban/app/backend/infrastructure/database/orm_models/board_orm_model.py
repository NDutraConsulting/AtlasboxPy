from __future__ import annotations

from atlasboxpy_db import SessionOpener, session_scope
from sqlalchemy import select

from ..entities import Board
from ..tables.board_table import BoardRow

# This class never imports KANBAN_DB_QUANTUM — it only ever receives an
# already-resolved `sessions` opener. Only kanban_storages.py (the
# composition layer) and main.py need the quantum itself, to ask
# DBQuantumRegistry for that opener in the first place. That's the
# decoupling: this file can't accidentally depend on which database
# "boards" lives in, because it's never given the means to.


def _to_entity(row: BoardRow) -> Board:
    return Board(id=row.id, name=row.name)


class SQLAlchemyBoardStorage:
    """Owns the `boards` table. `BoardRepository` calls this directly —
    no separate interface class: the contract is this class's own public
    methods and their `Board`/`None` return types, not a formal
    `typing.Protocol`. There's exactly one implementation and no plan for
    a second; a Protocol here would document a promise nothing keeps."""

    def __init__(self, sessions: SessionOpener) -> None:
        self._sessions = sessions

    async def get_by_id(self, board_id: str) -> Board | None:
        async with session_scope(self._sessions) as session:
            row = await session.get(BoardRow, board_id)
            return _to_entity(row) if row is not None else None

    async def list_all(self) -> list[Board]:
        async with session_scope(self._sessions) as session:
            rows = (await session.execute(select(BoardRow))).scalars().all()
            return [_to_entity(row) for row in rows]

    async def create(self, board_id: str, name: str) -> Board:
        async with session_scope(self._sessions) as session:
            session.add(BoardRow(id=board_id, name=name))
        return Board(id=board_id, name=name)

    async def delete(self, board_id: str) -> None:
        async with session_scope(self._sessions) as session:
            row = await session.get(BoardRow, board_id)
            if row is not None:
                await session.delete(row)
