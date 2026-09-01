"""BoardRepository — the `boards` table's own repository: entity-scoped
CRUD plus a read-through cache for `get_by_id`, nothing else. It has no
idea `Column` or `Card` exist. Assembling a board with its columns and
cards nested inside, or tallying column/card counts across every board,
is orchestration across entities — that's `KanbanService`'s job now (see
its own docstring for why), not a repository's.

Cache values are stored as plain dicts (`dataclasses.asdict`), not the
`Board` dataclass itself: `atlasboxpy_repository`'s `CacheBackend`
contract requires JSON-serializable values (a real Redis backend has to
serialize regardless), so caching a dataclass instance directly would
work today under `BareMetalCacheBackend` but break silently the moment
`cache_driver` flips to `CacheDriver.REDIS`.
"""

from __future__ import annotations

import dataclasses

from atlasboxpy_repository import BaseRepository, CacheDriver, CacheEnv

from ..database.entities import Board
from ..database.kanban_storages import build_board_storage

# --- cache configuration for this repository ---
cache_driver: CacheDriver = CacheDriver.BARE_METAL      # CacheEnv.REDIS
cache_env: CacheEnv = CacheEnv.LOCAL                    # CacheEnv.REMOTE
# -------------------------------------------------


class BoardRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__(cache_driver=cache_driver, cache_env=cache_env)
        self._storage = build_board_storage()

    @staticmethod
    def _cache_key(board_id: str) -> str:
        return f"kanban:board:{board_id}"

    async def create(self, board_id: str, name: str) -> Board:
        return await self._storage.create(board_id, name)

    async def get_by_id(self, board_id: str) -> Board | None:
        cache_key = self._cache_key(board_id)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return Board(**cached)
        board = await self._storage.get_by_id(board_id)
        if board is not None:
            await self.cache.set(cache_key, dataclasses.asdict(board))
        return board

    async def list_all(self) -> list[Board]:
        return await self._storage.list_all()

    async def delete(self, board_id: str) -> None:
        await self._storage.delete(board_id)
        await self.cache.invalidate(self._cache_key(board_id))
