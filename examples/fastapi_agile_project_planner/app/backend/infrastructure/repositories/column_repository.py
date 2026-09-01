"""ColumnRepository — the `columns` table's own repository: entity-scoped
CRUD plus a read-through cache for `list_for_board`. It has no idea a
board's name or its cards exist — `KanbanService` orchestrates this
alongside `BoardRepository`/`CardRepository` to assemble a board.

See `BoardRepository`'s docstring for why cache values are stored as
plain dicts, not `Column` dataclass instances directly.
"""

from __future__ import annotations

import dataclasses

from atlasboxpy_repository import BaseRepository, CacheDriver, CacheEnv

from ..database.entities import Column
from ..database.kanban_storages import build_column_storage

# --- cache configuration for this repository ---
cache_driver: CacheDriver = CacheDriver.BARE_METAL      # CacheEnv.REDIS
cache_env: CacheEnv = CacheEnv.LOCAL                    # CacheEnv.REMOTE
# -------------------------------------------------


class ColumnRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__(cache_driver=cache_driver, cache_env=cache_env)
        self._storage = build_column_storage()

    @staticmethod
    def _cache_key(board_id: str) -> str:
        return f"kanban:columns:{board_id}"

    async def create(self, board_id: str, name: str, position: int) -> Column:
        column = await self._storage.create(board_id, name, position)
        await self.cache.invalidate(self._cache_key(board_id))
        return column

    async def get_by_id(self, column_id: str) -> Column | None:
        return await self._storage.get_by_id(column_id)

    async def list_for_board(self, board_id: str) -> list[Column]:
        cache_key = self._cache_key(board_id)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return [Column(**c) for c in cached]
        columns = await self._storage.list_for_board(board_id)
        await self.cache.set(cache_key, [dataclasses.asdict(c) for c in columns])
        return columns

    async def count_grouped_by_board(self) -> dict[str, int]:
        return await self._storage.count_grouped_by_board()

    async def delete(self, column_id: str, board_id: str) -> None:
        await self._storage.delete(column_id)
        await self.cache.invalidate(self._cache_key(board_id))

    async def delete_for_board(self, board_id: str) -> None:
        await self._storage.delete_for_board(board_id)
        await self.cache.invalidate(self._cache_key(board_id))
