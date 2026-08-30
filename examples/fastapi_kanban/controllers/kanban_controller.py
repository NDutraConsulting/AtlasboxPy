"""KanbanController wraps KanbanService, which owns the whole board/
column/card aggregate. With one service instead of two, the controller no
longer has to assemble cross-service responses or enforce cross-service
rules — that logic lives in KanbanService now, because Board/Column/Card
were never really independent (see kanban_service.py's docstring).

What's still the controller's job, and always will be regardless of how
many services back it:

    Translate: a service never raises DomainError or knows
    validator_gateway exists — it returns a ServiceResult. `_unwrap()` is
    the one place a ServiceResult's status/msg/error_code becomes either
    a plain return value or a raised DomainError, which is what
    KanbanValidatorGateway's handle() then classifies and formats.

If a genuinely independent capability shows up later (a state machine, a
recommendation engine — something sharing no data with this aggregate),
*that* is what would get its own decoupled service, with this controller
(or a ServiceBus alongside it) orchestrating between it and KanbanService.
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

from ..services import KanbanService, ServiceResult, ServiceStatus

_ERROR_CODE_TO_DOMAIN: dict[str, type[DomainError]] = {
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "validation_failed": ValidationFailedError,
    "upstream_error": UpstreamServiceError,
}


class KanbanController(BaseController):
    def __init__(self, service: KanbanService) -> None:
        super().__init__()
        self.service = service

    # --- boards ---

    async def create_board(self, payload: Any) -> dict[str, Any]:
        return self._unwrap(await self.service.create_board(payload.name))

    async def list_boards(self) -> list[dict[str, Any]]:
        return self._unwrap(await self.service.list_boards())

    async def get_board(self, board_id: str) -> dict[str, Any]:
        return self._unwrap(await self.service.get_board(board_id))

    async def delete_board(self, board_id: str) -> None:
        self._unwrap(await self.service.delete_board(board_id))

    async def add_column(self, board_id: str, payload: Any) -> dict[str, Any]:
        return self._unwrap(await self.service.add_column(board_id, payload.name))

    async def delete_column(self, board_id: str, column_id: str) -> None:
        self._unwrap(await self.service.delete_column(board_id, column_id))

    # --- cards ---

    async def create_card(self, board_id: str, payload: Any) -> dict[str, Any]:
        return self._unwrap(
            await self.service.create_card(
                board_id, payload.column_id, payload.title, payload.description
            )
        )

    async def update_card(self, card_id: str, payload: Any) -> dict[str, Any]:
        return self._unwrap(
            await self.service.update_card(card_id, payload.title, payload.description)
        )

    async def move_card(self, card_id: str, payload: Any) -> dict[str, Any]:
        return self._unwrap(await self.service.move_card(card_id, payload.column_id))

    async def delete_card(self, card_id: str) -> None:
        self._unwrap(await self.service.delete_card(card_id))

    # --- translation ---

    def _unwrap(self, result: ServiceResult) -> Any:
        if result.status == ServiceStatus.SUCCESS:
            return result.result.data if result.result is not None else None
        if result.status == ServiceStatus.TIMEOUT:
            raise UpstreamServiceError(result.msg)
        domain_error_type = _ERROR_CODE_TO_DOMAIN.get(result.error_code, UnprocessableError)
        raise domain_error_type(result.msg)
