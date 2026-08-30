"""KanbanController — the only class in this demo allowed to call both
BoardService and CardService (and the only one allowed to call a service
at all; nothing else does). Its two jobs:

1. Orchestrate: assemble a response from more than one service (e.g.
   get_board nests CardService's cards inside BoardService's columns),
   and enforce cross-entity rules neither service alone can see (e.g.
   "a column with cards can't be deleted" needs both services' data).
2. Translate: a service never raises DomainError or knows
   validator_gateway exists — it returns a ServiceResult. `_unwrap()` is
   the one place a ServiceResult's status/msg/error_code becomes either a
   plain return value or a raised DomainError, which is what
   KanbanValidatorGateway's handle() then classifies and formats.
"""

from __future__ import annotations

from typing import Any

from validator_gateway import (
    BaseController,
    ConflictError,
    DomainError,
    NotFoundError,
    UnprocessableError,
    UpstreamServiceError,
    ValidationFailedError,
)

from ..services import BoardService, CardService, ServiceResult, ServiceStatus

_ERROR_CODE_TO_DOMAIN: dict[str, type[DomainError]] = {
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "validation_failed": ValidationFailedError,
    "upstream_error": UpstreamServiceError,
}


class KanbanController(BaseController):
    def __init__(self, board_service: BoardService, card_service: CardService) -> None:
        super().__init__()
        self.board_service = board_service
        self.card_service = card_service

    # --- boards ---

    async def create_board(self, payload: Any) -> dict[str, Any]:
        return self._unwrap(await self.board_service.create_board(payload.name))

    async def list_boards(self) -> list[dict[str, Any]]:
        boards = self._unwrap(await self.board_service.list_boards())
        counts = self._unwrap(await self.card_service.count_cards_grouped_by_board())
        return [{**board, "card_count": counts.get(board["id"], 0)} for board in boards]

    async def get_board(self, board_id: str) -> dict[str, Any]:
        board = self._unwrap(await self.board_service.get_board(board_id))
        cards = self._unwrap(await self.card_service.list_cards_for_board(board_id))

        cards_by_column: dict[str, list[dict[str, Any]]] = {}
        for card in cards:
            cards_by_column.setdefault(card["column_id"], []).append(
                {
                    "id": card["id"],
                    "title": card["title"],
                    "description": card["description"],
                    "column_id": card["column_id"],
                }
            )
        board["columns"] = [
            {**column, "cards": cards_by_column.get(column["id"], [])} for column in board["columns"]
        ]
        return board

    async def delete_board(self, board_id: str) -> None:
        self._unwrap(await self.board_service.delete_board(board_id))

    async def add_column(self, board_id: str, payload: Any) -> dict[str, Any]:
        column = self._unwrap(await self.board_service.add_column(board_id, payload.name))
        return {**column, "cards": []}

    async def delete_column(self, board_id: str, column_id: str) -> None:
        # Cross-service business rule: a column with cards can't be
        # deleted. BoardService can't see the `cards` table and
        # CardService doesn't own columns, so only the controller — which
        # is allowed to call both — can enforce this.
        self._unwrap(await self.board_service.column_exists(board_id, column_id))
        card_count = self._unwrap(await self.card_service.count_cards_in_column(column_id))
        if card_count:
            raise ConflictError(
                f"Column {column_id} still has {card_count} card(s) — move or delete them first"
            )
        self._unwrap(await self.board_service.delete_column(board_id, column_id))

    # --- cards ---

    async def create_card(self, board_id: str, payload: Any) -> dict[str, Any]:
        # column_exists also confirms the board itself exists (BoardService
        # rejects columns whose board_id doesn't match).
        self._unwrap(await self.board_service.column_exists(board_id, payload.column_id))
        return self._unwrap(
            await self.card_service.create_card(
                board_id, payload.column_id, payload.title, payload.description
            )
        )

    async def update_card(self, card_id: str, payload: Any) -> dict[str, Any]:
        return self._unwrap(
            await self.card_service.update_card(card_id, payload.title, payload.description)
        )

    async def move_card(self, card_id: str, payload: Any) -> dict[str, Any]:
        card = self._unwrap(await self.card_service.get_card(card_id))
        self._unwrap(await self.board_service.column_exists(card["board_id"], payload.column_id))
        return self._unwrap(await self.card_service.move_card(card_id, payload.column_id))

    async def delete_card(self, card_id: str) -> None:
        self._unwrap(await self.card_service.delete_card(card_id))

    # --- translation ---

    def _unwrap(self, result: ServiceResult) -> Any:
        if result.status == ServiceStatus.SUCCESS:
            return result.result.data if result.result is not None else None
        if result.status == ServiceStatus.TIMEOUT:
            raise UpstreamServiceError(result.msg)
        domain_error_type = _ERROR_CODE_TO_DOMAIN.get(result.error_code, UnprocessableError)
        raise domain_error_type(result.msg)
