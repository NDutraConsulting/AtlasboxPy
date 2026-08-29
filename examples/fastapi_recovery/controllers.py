from validator_gateway import BaseController

from .services import SyncService


class SyncController(BaseController):
    def __init__(self, service: SyncService) -> None:
        super().__init__()
        self.service = service

    async def sync_user(self, user_id: str) -> dict:
        return await self.service.sync_user(user_id)
