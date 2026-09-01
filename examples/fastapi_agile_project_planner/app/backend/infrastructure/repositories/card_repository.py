"""CardRepository — the `cards` table's own repository: entity-scoped
CRUD plus a read-through cache for `list_for_board`. It knows a card has
a `board_id`/`column_id` (foreign keys, nothing more) but nothing about
`Board` or `Column` beyond that — `KanbanService` orchestrates this
alongside `BoardRepository`/`ColumnRepository` to assemble a board.

See `BoardRepository`'s docstring for why cache values are stored as
plain dicts, not `Card` dataclass instances directly.
"""

from __future__ import annotations

import dataclasses

from atlasboxpy_repository import BaseRepository, CacheDriver, CacheEnv

from ..database.entities import Card
from ..database.kanban_storages import build_card_storage

# --- cache configuration for this repository ---
cache_driver: CacheDriver = CacheDriver.BARE_METAL      # CacheEnv.REDIS
cache_env: CacheEnv = CacheEnv.LOCAL                    # CacheEnv.REMOTE
# -------------------------------------------------


class CardRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__(cache_driver=cache_driver, cache_env=cache_env)
        self._storage = build_card_storage()

    @staticmethod
    def _cache_key(board_id: str) -> str:
        return f"kanban:cards:{board_id}"

    async def create(
        self, board_id: str, column_id: str, title: str, description: str
    ) -> Card:
        card = await self._storage.create(board_id, column_id, title, description)
        await self.cache.invalidate(self._cache_key(board_id))
        return card

    async def get_by_id(self, card_id: str) -> Card | None:
        return await self._storage.get_by_id(card_id)

    async def list_for_board(self, board_id: str) -> list[Card]:
        cache_key = self._cache_key(board_id)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return [Card(**c) for c in cached]
        cards = await self._storage.list_for_board(board_id)
        await self.cache.set(cache_key, [dataclasses.asdict(c) for c in cards])
        return cards

    async def count_for_column(self, column_id: str) -> int:
        return await self._storage.count_for_column(column_id)

    async def count_grouped_by_board(self) -> dict[str, int]:
        return await self._storage.count_grouped_by_board()

    async def update(
        self, card_id: str, title: str | None, description: str | None
    ) -> Card | None:
        card = await self._storage.update(card_id, title, description)
        if card is not None:
            await self.cache.invalidate(self._cache_key(card.board_id))
        return card

    async def move(self, card_id: str, column_id: str) -> Card | None:
        card = await self._storage.move(card_id, column_id)
        if card is not None:
            await self.cache.invalidate(self._cache_key(card.board_id))
        return card

    async def update_tags(self, card_id: str, tags: list[str]) -> Card | None:
        card = await self._storage.update_tags(card_id, tags)
        if card is not None:
            await self.cache.invalidate(self._cache_key(card.board_id))
        return card

    async def delete(self, card_id: str) -> Card | None:
        card = await self._storage.delete(card_id)
        if card is not None:
            await self.cache.invalidate(self._cache_key(card.board_id))
        return card

    async def delete_for_board(self, board_id: str) -> None:
        await self._storage.delete_for_board(board_id)
        await self.cache.invalidate(self._cache_key(board_id))
