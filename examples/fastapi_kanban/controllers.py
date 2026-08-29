from validator_gateway import BaseController

from .models import (
    CreateBoardRequest,
    CreateCardRequest,
    CreateColumnRequest,
    MoveCardRequest,
    UpdateCardRequest,
)
from .services import KanbanService


class BoardsController(BaseController):
    """Backs the "boards" frontend feature: the boards list page."""

    def __init__(self, service: KanbanService) -> None:
        super().__init__()
        self.service = service

    async def create_board(self, payload: CreateBoardRequest):
        return await self.service.create_board(payload.name)

    async def list_boards(self):
        return await self.service.list_boards()


class BoardController(BaseController):
    """Backs the "board" frontend feature: one board's columns and cards."""

    def __init__(self, service: KanbanService) -> None:
        super().__init__()
        self.service = service

    async def get_board(self, board_id: str):
        return await self.service.get_board(board_id)

    async def delete_board(self, board_id: str) -> None:
        await self.service.delete_board(board_id)

    async def add_column(self, board_id: str, payload: CreateColumnRequest):
        return await self.service.add_column(board_id, payload.name)

    async def delete_column(self, board_id: str, column_id: str) -> None:
        await self.service.delete_column(board_id, column_id)

    async def create_card(self, board_id: str, payload: CreateCardRequest):
        return await self.service.create_card(
            board_id, payload.column_id, payload.title, payload.description
        )

    async def update_card(self, card_id: str, payload: UpdateCardRequest):
        return await self.service.update_card(card_id, payload.title, payload.description)

    async def move_card(self, card_id: str, payload: MoveCardRequest):
        return await self.service.move_card(card_id, payload.column_id)

    async def delete_card(self, card_id: str) -> None:
        await self.service.delete_card(card_id)
