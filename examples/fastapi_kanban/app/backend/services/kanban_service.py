"""KanbanService owns the business rules AND the domain assembly for the
whole board/column/card aggregate — Board, Column, and Card are managed
together because they're one bounded context, not three.

Persistence is NOT behind one repository that assembles a board itself:
`BoardRepository`, `ColumnRepository`, and `CardRepository`
(infrastructure/repositories/) are each a genuine entity-scoped
repository — their own `atlasboxpy_repository.BaseRepository` subclass,
own cache, own storage — and none of them knows the other two exist.
Fetching "a board" (a `Board` plus its `Column`s plus its `Card`s) is an
orchestration decision, and orchestrating across entities is a service's
job, not a repository's: this class calls all three repositories
directly, concurrently via `asyncio.gather` wherever the lookups don't
depend on each other, and builds the JSON-shaped dicts `KanbanController`
returns.

What lives here: validation (title length, empty names), the cross-entity
rules a single entity-scoped repository can't express on its own (a
column has to belong to the board a card claims it does, a column can't
be deleted while cards still reference it) — and now also the read/write
orchestration and dict-shaping.

Every public method returns a ServiceResult. KanbanService never raises
DomainError and never knows atlasboxpy_controller exists — that translation
is KanbanController's job.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from ..infrastructure.database.entities import Card
from ..infrastructure.repositories import (
    BoardRepository,
    CardRepository,
    ColumnRepository,
)
from .results import ServiceResult, translate_db_errors

DEFAULT_COLUMNS = ["To Do", "In Progress", "Done"]
MAX_TITLE_LENGTH = 10


def _validate_title(title: str) -> str | None:
    if not title.strip():
        return "Card title must not be empty"
    if len(title) > MAX_TITLE_LENGTH:
        return f"Card title must be at most {MAX_TITLE_LENGTH} characters (got {len(title)})"
    return None


def _card_dict(card: Card) -> dict[str, Any]:
    return {
        "id": card.id,
        "board_id": card.board_id,
        "column_id": card.column_id,
        "title": card.title,
        "description": card.description,
    }


class KanbanService:
    def __init__(self) -> None:
        self._boards = BoardRepository()
        self._columns = ColumnRepository()
        self._cards = CardRepository()

    # --- boards ---

    @translate_db_errors
    async def create_board(self, name: str) -> ServiceResult:
        if not name.strip():
            return ServiceResult.error("Board name must not be empty", code="validation_failed")
        board_id = str(uuid.uuid4())
        await self._boards.create(board_id, name)
        await asyncio.gather(
            *(
                self._columns.create(board_id, col_name, position)
                for position, col_name in enumerate(DEFAULT_COLUMNS)
            )
        )
        return await self.get_board(board_id)

    @translate_db_errors
    async def list_boards(self) -> ServiceResult:
        boards, column_counts, card_counts = await asyncio.gather(
            self._boards.list_all(),
            self._columns.count_grouped_by_board(),
            self._cards.count_grouped_by_board(),
        )
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
        board, columns, cards = await asyncio.gather(
            self._boards.get_by_id(board_id),
            self._columns.list_for_board(board_id),
            self._cards.list_for_board(board_id),
        )
        if board is None:
            return ServiceResult.error(f"Board {board_id} not found", code="not_found")

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
        board = await self._boards.get_by_id(board_id)
        if board is None:
            return ServiceResult.error(f"Board {board_id} not found", code="not_found")
        # Board deleted first, deliberately — not cards/columns first. If a
        # failure happens between here and the cascade below, this ordering
        # fails *safe*: the board is already gone (its cache entry
        # invalidated, its row deleted), so it's unreachable via get_board
        # regardless of whether the cascade below completes — no stale
        # "board still exists with all its data" response is possible. The
        # opposite ordering (cards/columns first) can leave an orphaned,
        # still-reachable board with a stale cached response if the final
        # board-delete step is the one that fails. The trade-off: a failed
        # cascade below leaves orphaned card/column rows referencing a
        # board_id nothing can reach again — inert, not a correctness bug,
        # but real; this method still reports the failure rather than
        # hiding it, so it's visible to fix (a cleanup pass keyed on
        # orphaned board_ids), not silently swept under a "success".
        await self._boards.delete(board_id)
        await asyncio.gather(
            self._cards.delete_for_board(board_id),
            self._columns.delete_for_board(board_id),
        )
        return ServiceResult.ok(None)

    # --- columns ---

    @translate_db_errors
    async def add_column(self, board_id: str, name: str) -> ServiceResult:
        if not name.strip():
            return ServiceResult.error("Column name must not be empty", code="validation_failed")
        board, existing_columns = await asyncio.gather(
            self._boards.get_by_id(board_id),
            self._columns.list_for_board(board_id),
        )
        if board is None:
            return ServiceResult.error(f"Board {board_id} not found", code="not_found")
        existing_names = [c.name for c in existing_columns]
        if name in existing_names:
            return ServiceResult.error(
                f"Column {name!r} already exists on this board", code="conflict"
            )
        column = await self._columns.create(board_id, name, position=len(existing_names))
        return ServiceResult.ok({"id": column.id, "name": column.name, "cards": []})

    @translate_db_errors
    async def delete_column(self, board_id: str, column_id: str) -> ServiceResult:
        column = await self._columns.get_by_id(column_id)
        if column is None or column.board_id != board_id:
            return ServiceResult.error(
                f"Column {column_id} not found on board {board_id}", code="not_found"
            )
        card_count = await self._cards.count_for_column(column_id)
        if card_count:
            return ServiceResult.error(
                f"Column {column_id} still has {card_count} card(s) — move or delete them first",
                code="conflict",
            )
        await self._columns.delete(column_id, board_id)
        return ServiceResult.ok(None)

    # --- cards ---

    @translate_db_errors
    async def create_card(
        self, board_id: str, column_id: str, title: str, description: str
    ) -> ServiceResult:
        error = _validate_title(title)
        if error:
            return ServiceResult.error(error, code="validation_failed")
        column = await self._columns.get_by_id(column_id)
        if column is None or column.board_id != board_id:
            return ServiceResult.error(
                f"Column {column_id} not found on board {board_id}", code="not_found"
            )
        card = await self._cards.create(board_id, column_id, title, description)
        return ServiceResult.ok(_card_dict(card))

    @translate_db_errors
    async def update_card(
        self, card_id: str, title: str | None, description: str | None
    ) -> ServiceResult:
        if title is not None:
            error = _validate_title(title)
            if error:
                return ServiceResult.error(error, code="validation_failed")
        card = await self._cards.update(card_id, title, description)
        if card is None:
            return ServiceResult.error(f"Card {card_id} not found", code="not_found")
        return ServiceResult.ok(_card_dict(card))

    @translate_db_errors
    async def move_card(self, card_id: str, column_id: str) -> ServiceResult:
        card = await self._cards.get_by_id(card_id)
        if card is None:
            return ServiceResult.error(f"Card {card_id} not found", code="not_found")
        column = await self._columns.get_by_id(column_id)
        if column is None or column.board_id != card.board_id:
            return ServiceResult.error(
                f"Column {column_id} not found on board {card.board_id}", code="not_found"
            )
        updated = await self._cards.move(card_id, column_id)
        return ServiceResult.ok(_card_dict(updated) if updated is not None else None)

    @translate_db_errors
    async def delete_card(self, card_id: str) -> ServiceResult:
        card = await self._cards.delete(card_id)
        if card is None:
            return ServiceResult.error(f"Card {card_id} not found", code="not_found")
        return ServiceResult.ok(None)
