from validator_gateway import BaseController

from ..models import CreateBoardRequest
from ..services import KanbanService


class BoardsController(BaseController):
    """Backs the "boards" frontend feature: the boards list page."""

    def __init__(self, service: KanbanService) -> None:
        super().__init__()
        self.service = service

    async def create_board(self, payload: CreateBoardRequest):
        return await self.service.create_board(payload.name)

    async def list_boards(self):
        return await self.service.list_boards()
