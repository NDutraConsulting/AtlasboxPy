"""Owns boards and their columns — its own tables, nothing else. Never
imports CardService, never imports a controller, never raises a
DomainError. Every public method returns a ServiceResult."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy import delete as sql_delete

from ..db import SessionFactory, session_scope
from ..orm_models import BoardRow, ColumnRow
from .db_simulation import check_simulation, translate_db_errors
from .results import ServiceResult

DEFAULT_COLUMNS = ["To Do", "In Progress", "Done"]


class BoardService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    @translate_db_errors
    async def create_board(self, name: str) -> ServiceResult:
        if not name.strip():
            return ServiceResult.error("Board name must not be empty", code="validation_failed")
        await check_simulation()
        board_id = str(uuid.uuid4())
        async with session_scope(self._session_factory) as session:
            session.add(BoardRow(id=board_id, name=name))
            for position, col_name in enumerate(DEFAULT_COLUMNS):
                session.add(
                    ColumnRow(
                        id=str(uuid.uuid4()), board_id=board_id, name=col_name, position=position
                    )
                )
        return await self.get_board(board_id)

    @translate_db_errors
    async def list_boards(self) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            boards = (await session.execute(select(BoardRow))).scalars().all()
            columns = (await session.execute(select(ColumnRow))).scalars().all()

        column_counts: dict[str, int] = {}
        for column in columns:
            column_counts[column.board_id] = column_counts.get(column.board_id, 0) + 1

        data = [
            {"id": board.id, "name": board.name, "column_count": column_counts.get(board.id, 0)}
            for board in boards
        ]
        return ServiceResult.ok(data, type_="array")

    @translate_db_errors
    async def get_board(self, board_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            board = await session.get(BoardRow, board_id)
            if board is None:
                return ServiceResult.error(f"Board {board_id} not found", code="not_found")
            columns = (
                (
                    await session.execute(
                        select(ColumnRow)
                        .where(ColumnRow.board_id == board_id)
                        .order_by(ColumnRow.position)
                    )
                )
                .scalars()
                .all()
            )
            data = {
                "id": board.id,
                "name": board.name,
                "columns": [{"id": c.id, "name": c.name} for c in columns],
            }
        return ServiceResult.ok(data)

    @translate_db_errors
    async def delete_board(self, board_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            board = await session.get(BoardRow, board_id)
            if board is None:
                return ServiceResult.error(f"Board {board_id} not found", code="not_found")
            await session.execute(sql_delete(ColumnRow).where(ColumnRow.board_id == board_id))
            await session.delete(board)
        return ServiceResult.ok(None)

    @translate_db_errors
    async def add_column(self, board_id: str, name: str) -> ServiceResult:
        if not name.strip():
            return ServiceResult.error("Column name must not be empty", code="validation_failed")
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            board = await session.get(BoardRow, board_id)
            if board is None:
                return ServiceResult.error(f"Board {board_id} not found", code="not_found")
            existing_columns = (
                (await session.execute(select(ColumnRow).where(ColumnRow.board_id == board_id)))
                .scalars()
                .all()
            )
            if any(c.name == name for c in existing_columns):
                return ServiceResult.error(
                    f"Column {name!r} already exists on this board", code="conflict"
                )
            column = ColumnRow(
                id=str(uuid.uuid4()), board_id=board_id, name=name, position=len(existing_columns)
            )
            session.add(column)
            column_id = column.id
        return ServiceResult.ok({"id": column_id, "name": name})

    @translate_db_errors
    async def delete_column(self, board_id: str, column_id: str) -> ServiceResult:
        """Unconditionally deletes the column. Whether it's *safe* to
        delete (e.g. no cards still reference it) is not this service's
        call to make — it has no visibility into the `cards` table. That
        check is the controller's job, orchestrating both services before
        it ever calls this method."""
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            column = await session.get(ColumnRow, column_id)
            if column is None or column.board_id != board_id:
                return ServiceResult.error(
                    f"Column {column_id} not found on board {board_id}", code="not_found"
                )
            await session.delete(column)
        return ServiceResult.ok(None)

    @translate_db_errors
    async def column_exists(self, board_id: str, column_id: str) -> ServiceResult:
        """A read-only existence check the controller uses to validate a
        column before an operation on a *different* service (e.g.
        CardService.create_card) — this is how cross-entity validation
        happens without BoardService and CardService calling each other."""
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            column = await session.get(ColumnRow, column_id)
        if column is None or column.board_id != board_id:
            return ServiceResult.error(
                f"Column {column_id} not found on board {board_id}", code="not_found"
            )
        return ServiceResult.ok({"id": column.id})
