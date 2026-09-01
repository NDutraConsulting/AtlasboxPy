from __future__ import annotations

import json
import uuid

from atlasboxpy_db import SessionOpener, session_scope
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select

from ..entities import Card
from ..tables.card_table import CardRow


def _to_entity(row: CardRow) -> Card:
    return Card(
        id=row.id,
        board_id=row.board_id,
        column_id=row.column_id,
        title=row.title,
        description=row.description,
        tags=json.loads(row.tags),
    )


class SQLAlchemyCardStorage:
    """Owns the `cards` table. `CardRepository` calls this directly —
    no separate interface class: the contract is this class's own public
    methods and their `Card`/`None` return types, not a formal
    `typing.Protocol`. There's exactly one implementation and no plan for
    a second; a Protocol here would document a promise nothing keeps."""

    def __init__(self, sessions: SessionOpener) -> None:
        self._sessions = sessions

    async def get_by_id(self, card_id: str) -> Card | None:
        async with session_scope(self._sessions) as session:
            row = await session.get(CardRow, card_id)
            return _to_entity(row) if row is not None else None

    async def list_for_board(self, board_id: str) -> list[Card]:
        async with session_scope(self._sessions) as session:
            result = await session.execute(select(CardRow).where(CardRow.board_id == board_id))
            return [_to_entity(row) for row in result.scalars().all()]

    async def count_for_column(self, column_id: str) -> int:
        async with session_scope(self._sessions) as session:
            result = await session.execute(
                select(func.count()).select_from(CardRow).where(CardRow.column_id == column_id)
            )
            return result.scalar_one()

    async def count_grouped_by_board(self) -> dict[str, int]:
        async with session_scope(self._sessions) as session:
            rows = await session.execute(
                select(CardRow.board_id, func.count()).group_by(CardRow.board_id)
            )
            return {board_id: count for board_id, count in rows.all()}

    async def create(
        self, board_id: str, column_id: str, title: str, description: str
    ) -> Card:
        card_id = str(uuid.uuid4())
        async with session_scope(self._sessions) as session:
            session.add(
                CardRow(
                    id=card_id,
                    board_id=board_id,
                    column_id=column_id,
                    title=title,
                    description=description,
                    tags="[]",
                )
            )
        return Card(
            id=card_id,
            board_id=board_id,
            column_id=column_id,
            title=title,
            description=description,
            tags=[],
        )

    async def update(
        self, card_id: str, title: str | None, description: str | None
    ) -> Card | None:
        async with session_scope(self._sessions) as session:
            row = await session.get(CardRow, card_id)
            if row is None:
                return None
            if title is not None:
                row.title = title
            if description is not None:
                row.description = description
            entity = _to_entity(row)
        return entity

    async def update_tags(self, card_id: str, tags: list[str]) -> Card | None:
        async with session_scope(self._sessions) as session:
            row = await session.get(CardRow, card_id)
            if row is None:
                return None
            row.tags = json.dumps(tags)
            entity = _to_entity(row)
        return entity

    async def move(self, card_id: str, column_id: str) -> Card | None:
        async with session_scope(self._sessions) as session:
            row = await session.get(CardRow, card_id)
            if row is None:
                return None
            row.column_id = column_id
            entity = _to_entity(row)
        return entity

    async def delete(self, card_id: str) -> Card | None:
        async with session_scope(self._sessions) as session:
            row = await session.get(CardRow, card_id)
            if row is None:
                return None
            entity = _to_entity(row)
            await session.delete(row)
        return entity

    async def delete_for_board(self, board_id: str) -> None:
        async with session_scope(self._sessions) as session:
            await session.execute(sql_delete(CardRow).where(CardRow.board_id == board_id))
