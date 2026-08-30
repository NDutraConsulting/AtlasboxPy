"""Owns cards — its own table, nothing else. Never imports BoardService,
never imports a controller, never raises a DomainError. Cross-entity
checks (does this column belong to this board?) are the controller's job,
using BoardService.column_exists() — CardService just trusts the
column_id/board_id it's given. Every public method returns a
ServiceResult."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from ..db import SessionFactory, session_scope
from ..orm_models import CardRow
from .db_simulation import check_simulation, translate_db_errors
from .results import ServiceResult

MAX_TITLE_LENGTH = 10


def _validate_title(title: str) -> str | None:
    if not title.strip():
        return "Card title must not be empty"
    if len(title) > MAX_TITLE_LENGTH:
        return f"Card title must be at most {MAX_TITLE_LENGTH} characters (got {len(title)})"
    return None


def _as_dict(card: CardRow) -> dict[str, str]:
    return {
        "id": card.id,
        "board_id": card.board_id,
        "column_id": card.column_id,
        "title": card.title,
        "description": card.description,
    }


class CardService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    @translate_db_errors
    async def create_card(
        self, board_id: str, column_id: str, title: str, description: str
    ) -> ServiceResult:
        error = _validate_title(title)
        if error:
            return ServiceResult.error(error, code="validation_failed")
        await check_simulation()
        card = CardRow(
            id=str(uuid.uuid4()),
            board_id=board_id,
            column_id=column_id,
            title=title,
            description=description,
        )
        async with session_scope(self._session_factory) as session:
            session.add(card)
        return ServiceResult.ok(_as_dict(card))

    @translate_db_errors
    async def get_card(self, card_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            card = await session.get(CardRow, card_id)
        if card is None:
            return ServiceResult.error(f"Card {card_id} not found", code="not_found")
        return ServiceResult.ok(_as_dict(card))

    @translate_db_errors
    async def list_cards_for_board(self, board_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            cards = (
                (await session.execute(select(CardRow).where(CardRow.board_id == board_id)))
                .scalars()
                .all()
            )
        return ServiceResult.ok([_as_dict(c) for c in cards], type_="array")

    @translate_db_errors
    async def count_cards_in_column(self, column_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(CardRow).where(CardRow.column_id == column_id)
                )
            ).scalar_one()
        return ServiceResult.ok(count)

    @translate_db_errors
    async def count_cards_grouped_by_board(self) -> ServiceResult:
        """Used by the controller to assemble the boards-list summary —
        BoardService's list_boards() never touches this table itself."""
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            rows = (
                await session.execute(
                    select(CardRow.board_id, func.count()).group_by(CardRow.board_id)
                )
            ).all()
        return ServiceResult.ok({board_id: count for board_id, count in rows}, type_="map")

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
            data = _as_dict(card)
        return ServiceResult.ok(data)

    @translate_db_errors
    async def move_card(self, card_id: str, column_id: str) -> ServiceResult:
        await check_simulation()
        async with session_scope(self._session_factory) as session:
            card = await session.get(CardRow, card_id)
            if card is None:
                return ServiceResult.error(f"Card {card_id} not found", code="not_found")
            card.column_id = column_id
            data = _as_dict(card)
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
