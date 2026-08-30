"""KanbanService owns the whole board/column/card aggregate — Board,
Column, and Card are managed together because they're one bounded
context, not three: a card is meaningless without its board, and nearly
every interesting operation crosses between them (get_board nests cards
inside columns; deleting a column has to know whether cards still
reference it; moving a card has to confirm the target column belongs to
the card's own board). Splitting this into one service per table would
just relocate that coupling into the caller as repetitive glue code,
without actually removing it.

A genuinely independent capability — something with its own lifecycle
that shares no data with this aggregate, like a state machine or a
recommendation engine — is what would earn its own decoupled service
instead, orchestrated by a ServiceBus/controller alongside this one.

Every public method returns a ServiceResult. KanbanService never raises
DomainError and never knows validator_gateway exists — that translation
is KanbanController's job.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select

from ..db import SessionFactory, session_scope
from ..orm_models import BoardRow, CardRow, ColumnRow
from .db_simulation import check_simulation, translate_db_errors
from .results import ServiceResult

DEFAULT_COLUMNS = ["To Do", "In Progress", "Done"]
MAX_TITLE_LENGTH = 10


def _validate_title(title: str) -> str | None:
    if not title.strip():
        return "Card title must not be empty"
    if len(title) > MAX_TITLE_LENGTH:
        return f"Card title must be at most {MAX_TITLE_LENGTH} characters (got {len(title)})"
    return None


def _card_dict(card: CardRow) -> dict[str, Any]:
    return {
        "id": card.id,
        "board_id": card.board_id,
        "column_id": card.column_id,
        "title": card.title,
        "description": card.description,
    }


class KanbanService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    # --- boards ---

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
            card_rows = (
                await session.execute(
                    select(CardRow.board_id, func.count()).group_by(CardRow.board_id)
                )
            ).all()

        column_counts: dict[str, int] = {}
        for column in columns:
            column_counts[column.board_id] = column_counts.get(column.board_id, 0) + 1
        card_counts = dict(card_rows)

        data = [
            {
                "id": board.id,
                "name": board.name,
                "column_count": column_counts.get(board.id, 0),
                "card_count": card_counts.get(board.id, 0),
            }
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
            cards = (
                (await session.execute(select(CardRow).where(CardRow.board_id == board_id)))
                .scalars()
                .all()
            )

            cards_by_column: dict[str, list[dict[str, Any]]] = {}
            for card in cards:
                cards_by_column.setdefault(card.column_id, []).append(
                    {
                        "id": card.id,
                        "title": card.title,
                        "description": card.description,
                        "column_id": card.column_id,
                    }
                )
            data = {
                "id": board.id,
                "name": board.name,
                "columns": [
                    {"id": c.id, "name": c.name, "cards": cards_by_column.get(c.id, [])}
                    for c in columns
                ],
            }
        return ServiceResult.ok(data)

    @translate_db_errors
    async def delete_board(self, board_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            board = await session.get(BoardRow, board_id)
            if board is None:
                return ServiceResult.error(f"Board {board_id} not found", code="not_found")
            await session.execute(sql_delete(CardRow).where(CardRow.board_id == board_id))
            await session.execute(sql_delete(ColumnRow).where(ColumnRow.board_id == board_id))
            await session.delete(board)
        return ServiceResult.ok(None)

    # --- columns ---

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
        return ServiceResult.ok({"id": column_id, "name": name, "cards": []})

    @translate_db_errors
    async def delete_column(self, board_id: str, column_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            column = await session.get(ColumnRow, column_id)
            if column is None or column.board_id != board_id:
                return ServiceResult.error(
                    f"Column {column_id} not found on board {board_id}", code="not_found"
                )
            card_count = (
                await session.execute(
                    select(func.count()).select_from(CardRow).where(CardRow.column_id == column_id)
                )
            ).scalar_one()
            if card_count:
                return ServiceResult.error(
                    f"Column {column_id} still has {card_count} card(s) — "
                    "move or delete them first",
                    code="conflict",
                )
            await session.delete(column)
        return ServiceResult.ok(None)

    # --- cards ---

    @translate_db_errors
    async def create_card(
        self, board_id: str, column_id: str, title: str, description: str
    ) -> ServiceResult:
        error = _validate_title(title)
        if error:
            return ServiceResult.error(error, code="validation_failed")
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            column = await session.get(ColumnRow, column_id)
            if column is None or column.board_id != board_id:
                return ServiceResult.error(
                    f"Column {column_id} not found on board {board_id}", code="not_found"
                )
            card = CardRow(
                id=str(uuid.uuid4()),
                board_id=board_id,
                column_id=column_id,
                title=title,
                description=description,
            )
            session.add(card)
        return ServiceResult.ok(_card_dict(card))

    @translate_db_errors
    async def update_card(
        self, card_id: str, title: str | None, description: str | None
    ) -> ServiceResult:
        if title is not None:
            error = _validate_title(title)
            if error:
                return ServiceResult.error(error, code="validation_failed")
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            card = await session.get(CardRow, card_id)
            if card is None:
                return ServiceResult.error(f"Card {card_id} not found", code="not_found")
            if title is not None:
                card.title = title
            if description is not None:
                card.description = description
            data = _card_dict(card)
        return ServiceResult.ok(data)

    @translate_db_errors
    async def move_card(self, card_id: str, column_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            card = await session.get(CardRow, card_id)
            if card is None:
                return ServiceResult.error(f"Card {card_id} not found", code="not_found")
            column = await session.get(ColumnRow, column_id)
            if column is None or column.board_id != card.board_id:
                return ServiceResult.error(
                    f"Column {column_id} not found on board {card.board_id}", code="not_found"
                )
            card.column_id = column_id
            data = _card_dict(card)
        return ServiceResult.ok(data)

    @translate_db_errors
    async def delete_card(self, card_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            card = await session.get(CardRow, card_id)
            if card is None:
                return ServiceResult.error(f"Card {card_id} not found", code="not_found")
            await session.delete(card)
        return ServiceResult.ok(None)
