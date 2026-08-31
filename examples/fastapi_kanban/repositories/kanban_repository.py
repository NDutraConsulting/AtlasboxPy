"""KanbanRepository owns every SQLAlchemy query in this app — KanbanService
never touches a session, a select(), or an ORM row directly. That
boundary is what makes caching possible without leaking into the service:
`get_board`, the one expensive assembled read (a board plus its columns
plus every card nested inside them), is cached via `self.cache` (see
BaseRepository), and every write method that can affect a board's data
invalidates that board's cache entry before returning. KanbanService just
calls repository methods; it has no idea a cache exists, let alone which
technology backs it.

The two constants right below the imports are this repository's own cache
config — see the atlasboxpy_repository package (packages/atlasboxpy_repository/)
for what each value means and what other drivers exist. Change them here,
not there: a different repository elsewhere in the app could reasonably
want a different cache technology, so the choice lives with the
repository making it, not with the shared base class.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from typing import Any

from atlasboxpy_repository import BaseRepository, CacheDriver, CacheEnv
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionFactory, get_default_session_factory, session_scope
from ..db_simulation import active_session_factory
from ..orm_models import BoardRow, CardRow, ColumnRow

# --- cache configuration for this repository ---
cache_driver: CacheDriver = CacheDriver.BARE_METAL      # CacheEnv.REDIS
cache_env: CacheEnv = CacheEnv.LOCAL                    # CacheEnv.REMOTE
# -------------------------------------------------


def _card_dict(card: CardRow) -> dict[str, Any]:
    return {
        "id": card.id,
        "board_id": card.board_id,
        "column_id": card.column_id,
        "title": card.title,
        "description": card.description,
    }


class KanbanRepository(BaseRepository):
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        super().__init__(cache_driver=cache_driver, cache_env=cache_env)
        # An explicit session_factory is for tests/tools that want a
        # specific one; KanbanService's normal construction path passes
        # none, so this resolves whatever main.py's create_app() most
        # recently registered via set_default_session_factory() — see
        # db.py's module docstring for why that's not passed as a
        # parameter through KanbanService/KanbanController.
        self._session_factory = session_factory or get_default_session_factory()

    @staticmethod
    def _board_cache_key(board_id: str) -> str:
        return f"kanban:board:{board_id}"

    def _session(self) -> AbstractAsyncContextManager[AsyncSession]:
        return session_scope(active_session_factory(self._session_factory))

    # --- boards ---

    async def create_board(self, board_id: str, name: str, default_columns: list[str]) -> None:
        async with self._session() as session:
            session.add(BoardRow(id=board_id, name=name))
            for position, col_name in enumerate(default_columns):
                session.add(
                    ColumnRow(
                        id=str(uuid.uuid4()), board_id=board_id, name=col_name, position=position
                    )
                )

    async def board_exists(self, board_id: str) -> bool:
        async with self._session() as session:
            return await session.get(BoardRow, board_id) is not None

    async def list_boards(self) -> list[dict[str, Any]]:
        async with self._session() as session:
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

        return [
            {
                "id": board.id,
                "name": board.name,
                "column_count": column_counts.get(board.id, 0),
                "card_count": card_counts.get(board.id, 0),
            }
            for board in boards
        ]

    async def get_board(self, board_id: str) -> dict[str, Any] | None:
        cache_key = self._board_cache_key(board_id)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached

        async with self._session() as session:
            board = await session.get(BoardRow, board_id)
            if board is None:
                return None
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

        await self.cache.set(cache_key, data)
        return data

    async def delete_board(self, board_id: str) -> bool:
        async with self._session() as session:
            board = await session.get(BoardRow, board_id)
            if board is None:
                return False
            await session.execute(sql_delete(CardRow).where(CardRow.board_id == board_id))
            await session.execute(sql_delete(ColumnRow).where(ColumnRow.board_id == board_id))
            await session.delete(board)
        await self.cache.invalidate(self._board_cache_key(board_id))
        return True

    # --- columns ---

    async def list_column_names(self, board_id: str) -> list[str]:
        async with self._session() as session:
            columns = (
                (await session.execute(select(ColumnRow).where(ColumnRow.board_id == board_id)))
                .scalars()
                .all()
            )
            return [c.name for c in columns]

    async def add_column(self, board_id: str, name: str, position: int) -> dict[str, Any]:
        async with self._session() as session:
            column = ColumnRow(id=str(uuid.uuid4()), board_id=board_id, name=name, position=position)
            session.add(column)
            column_id = column.id
        await self.cache.invalidate(self._board_cache_key(board_id))
        return {"id": column_id, "name": name, "cards": []}

    async def get_column(self, column_id: str) -> ColumnRow | None:
        async with self._session() as session:
            return await session.get(ColumnRow, column_id)

    async def count_cards_in_column(self, column_id: str) -> int:
        async with self._session() as session:
            return (
                await session.execute(
                    select(func.count()).select_from(CardRow).where(CardRow.column_id == column_id)
                )
            ).scalar_one()

    async def delete_column(self, column_id: str, board_id: str) -> None:
        async with self._session() as session:
            column = await session.get(ColumnRow, column_id)
            if column is not None:
                await session.delete(column)
        await self.cache.invalidate(self._board_cache_key(board_id))

    # --- cards ---

    async def get_card(self, card_id: str) -> CardRow | None:
        async with self._session() as session:
            return await session.get(CardRow, card_id)

    async def add_card(
        self, board_id: str, column_id: str, title: str, description: str
    ) -> dict[str, Any]:
        async with self._session() as session:
            card = CardRow(
                id=str(uuid.uuid4()),
                board_id=board_id,
                column_id=column_id,
                title=title,
                description=description,
            )
            session.add(card)
        await self.cache.invalidate(self._board_cache_key(board_id))
        return _card_dict(card)

    async def update_card(
        self, card_id: str, title: str | None, description: str | None
    ) -> dict[str, Any] | None:
        async with self._session() as session:
            card = await session.get(CardRow, card_id)
            if card is None:
                return None
            if title is not None:
                card.title = title
            if description is not None:
                card.description = description
            data = _card_dict(card)
        await self.cache.invalidate(self._board_cache_key(data["board_id"]))
        return data

    async def move_card(self, card_id: str, column_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            card = await session.get(CardRow, card_id)
            if card is None:
                return None
            card.column_id = column_id
            data = _card_dict(card)
        await self.cache.invalidate(self._board_cache_key(data["board_id"]))
        return data

    async def delete_card(self, card_id: str) -> bool:
        async with self._session() as session:
            card = await session.get(CardRow, card_id)
            if card is None:
                return False
            board_id = card.board_id
            await session.delete(card)
        await self.cache.invalidate(self._board_cache_key(board_id))
        return True
