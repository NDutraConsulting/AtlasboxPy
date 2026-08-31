"""KanbanService owns the business rules for the whole board/column/card
aggregate — Board, Column, and Card are managed together because they're
one bounded context, not three (see KanbanRepository's docstring for why
the data-access side is likewise unsplit).

This class does no SQLAlchemy of its own: every read or write goes through
KanbanRepository, which also owns the in-memory cache and its invalidation
(a repository concern, not a service one — the service shouldn't need to
know a cache exists any more than it needs to know the ORM does). What
lives here instead is validation (title length, empty names) and the
cross-entity rules a raw data access method can't express on its own — a
column has to belong to the board a card claims it does, a column can't be
deleted while cards still reference it.

Every public method returns a ServiceResult. KanbanService never raises
DomainError and never knows atlasboxpy_controller exists — that translation
is KanbanController's job.
"""

from __future__ import annotations

import uuid

from ..repositories import KanbanRepository
from .results import ServiceResult, translate_db_errors

DEFAULT_COLUMNS = ["To Do", "In Progress", "Done"]
MAX_TITLE_LENGTH = 10


def _validate_title(title: str) -> str | None:
    if not title.strip():
        return "Card title must not be empty"
    if len(title) > MAX_TITLE_LENGTH:
        return f"Card title must be at most {MAX_TITLE_LENGTH} characters (got {len(title)})"
    return None


class KanbanService:
    def __init__(self) -> None:
        self._repo = KanbanRepository()

    # --- boards ---

    @translate_db_errors
    async def create_board(self, name: str) -> ServiceResult:
        if not name.strip():
            return ServiceResult.error("Board name must not be empty", code="validation_failed")
        board_id = str(uuid.uuid4())
        await self._repo.create_board(board_id, name, DEFAULT_COLUMNS)
        return await self.get_board(board_id)

    @translate_db_errors
    async def list_boards(self) -> ServiceResult:
        data = await self._repo.list_boards()
        return ServiceResult.ok(data, type_="array")

    @translate_db_errors
    async def get_board(self, board_id: str) -> ServiceResult:
        data = await self._repo.get_board(board_id)
        if data is None:
            return ServiceResult.error(f"Board {board_id} not found", code="not_found")
        return ServiceResult.ok(data)

    @translate_db_errors
    async def delete_board(self, board_id: str) -> ServiceResult:
        deleted = await self._repo.delete_board(board_id)
        if not deleted:
            return ServiceResult.error(f"Board {board_id} not found", code="not_found")
        return ServiceResult.ok(None)

    # --- columns ---

    @translate_db_errors
    async def add_column(self, board_id: str, name: str) -> ServiceResult:
        if not name.strip():
            return ServiceResult.error("Column name must not be empty", code="validation_failed")
        if not await self._repo.board_exists(board_id):
            return ServiceResult.error(f"Board {board_id} not found", code="not_found")
        existing_names = await self._repo.list_column_names(board_id)
        if name in existing_names:
            return ServiceResult.error(
                f"Column {name!r} already exists on this board", code="conflict"
            )
        column = await self._repo.add_column(board_id, name, position=len(existing_names))
        return ServiceResult.ok(column)

    @translate_db_errors
    async def delete_column(self, board_id: str, column_id: str) -> ServiceResult:
        column = await self._repo.get_column(column_id)
        if column is None or column.board_id != board_id:
            return ServiceResult.error(
                f"Column {column_id} not found on board {board_id}", code="not_found"
            )
        card_count = await self._repo.count_cards_in_column(column_id)
        if card_count:
            return ServiceResult.error(
                f"Column {column_id} still has {card_count} card(s) — move or delete them first",
                code="conflict",
            )
        await self._repo.delete_column(column_id, board_id)
        return ServiceResult.ok(None)

    # --- cards ---

    @translate_db_errors
    async def create_card(
        self, board_id: str, column_id: str, title: str, description: str
    ) -> ServiceResult:
        error = _validate_title(title)
        if error:
            return ServiceResult.error(error, code="validation_failed")
        column = await self._repo.get_column(column_id)
        if column is None or column.board_id != board_id:
            return ServiceResult.error(
                f"Column {column_id} not found on board {board_id}", code="not_found"
            )
        card = await self._repo.add_card(board_id, column_id, title, description)
        return ServiceResult.ok(card)

    @translate_db_errors
    async def update_card(
        self, card_id: str, title: str | None, description: str | None
    ) -> ServiceResult:
        if title is not None:
            error = _validate_title(title)
            if error:
                return ServiceResult.error(error, code="validation_failed")
        card = await self._repo.update_card(card_id, title, description)
        if card is None:
            return ServiceResult.error(f"Card {card_id} not found", code="not_found")
        return ServiceResult.ok(card)

    @translate_db_errors
    async def move_card(self, card_id: str, column_id: str) -> ServiceResult:
        card = await self._repo.get_card(card_id)
        if card is None:
            return ServiceResult.error(f"Card {card_id} not found", code="not_found")
        column = await self._repo.get_column(column_id)
        if column is None or column.board_id != card.board_id:
            return ServiceResult.error(
                f"Column {column_id} not found on board {card.board_id}", code="not_found"
            )
        updated = await self._repo.move_card(card_id, column_id)
        return ServiceResult.ok(updated)

    @translate_db_errors
    async def delete_card(self, card_id: str) -> ServiceResult:
        deleted = await self._repo.delete_card(card_id)
        if not deleted:
            return ServiceResult.error(f"Card {card_id} not found", code="not_found")
        return ServiceResult.ok(None)
