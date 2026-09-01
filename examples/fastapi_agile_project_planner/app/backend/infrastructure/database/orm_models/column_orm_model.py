from __future__ import annotations

import uuid

from atlasboxpy_db import SessionOpener, session_scope
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select

from ..entities import Column
from ..tables.column_table import ColumnRow


def _to_entity(row: ColumnRow) -> Column:
    return Column(id=row.id, board_id=row.board_id, name=row.name, position=row.position)


class SQLAlchemyColumnStorage:
    """Owns the `columns` table. `ColumnRepository` calls this directly —
    no separate interface class: the contract is this class's own public
    methods and their `Column`/`None` return types, not a formal
    `typing.Protocol`. There's exactly one implementation and no plan for
    a second; a Protocol here would document a promise nothing keeps."""

    def __init__(self, sessions: SessionOpener) -> None:
        self._sessions = sessions

    async def get_by_id(self, column_id: str) -> Column | None:
        async with session_scope(self._sessions) as session:
            row = await session.get(ColumnRow, column_id)
            return _to_entity(row) if row is not None else None

    async def list_for_board(self, board_id: str) -> list[Column]:
        async with session_scope(self._sessions) as session:
            result = await session.execute(
                select(ColumnRow).where(ColumnRow.board_id == board_id).order_by(ColumnRow.position)
            )
            return [_to_entity(row) for row in result.scalars().all()]

    async def count_grouped_by_board(self) -> dict[str, int]:
        async with session_scope(self._sessions) as session:
            rows = await session.execute(
                select(ColumnRow.board_id, func.count()).group_by(ColumnRow.board_id)
            )
            return {board_id: count for board_id, count in rows.all()}

    async def create(self, board_id: str, name: str, position: int) -> Column:
        column_id = str(uuid.uuid4())
        async with session_scope(self._sessions) as session:
            session.add(ColumnRow(id=column_id, board_id=board_id, name=name, position=position))
        return Column(id=column_id, board_id=board_id, name=name, position=position)

    async def delete(self, column_id: str) -> None:
        async with session_scope(self._sessions) as session:
            row = await session.get(ColumnRow, column_id)
            if row is not None:
                await session.delete(row)

    async def delete_for_board(self, board_id: str) -> None:
        async with session_scope(self._sessions) as session:
            await session.execute(sql_delete(ColumnRow).where(ColumnRow.board_id == board_id))
