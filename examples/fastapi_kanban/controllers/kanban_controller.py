"""KanbanController wraps KanbanService, which owns the whole board/
column/card aggregate. With one service instead of two, the controller no
longer has to assemble cross-service responses or enforce cross-service
rules — that logic lives in KanbanService now, because Board/Column/Card
were never really independent (see kanban_service.py's docstring).

What's still the controller's job, and always will be regardless of how
many services back it:

    Translate: a service never raises DomainError or knows
    atlasboxpy_controller exists — it returns a ServiceResult. `_response_for()`
    is the one place a ServiceResult's status/msg/error_code becomes a
    SuccessResponse or ErrorResponse, built directly rather than raised —
    an expected outcome like "not found" is data, not something to raise.

    Decide: what a failure actually means for THIS method, and what (if
    anything) to do about it — a scenario-specific hint appended to a
    validation message, or a degraded fallback in place of reporting an
    outage. This lives here, inline in the method that has the context,
    rather than in an external classifier sniffing exception messages for
    substrings after the fact — each method already knows exactly what it
    can fail at and why.

BaseController wraps every method below in a try/except that would catch
anything genuinely unexpected (a real bug KanbanService didn't already
translate into a ServiceResult) — but the expected-outcome paths here never
raise at all.
"""

from __future__ import annotations

from typing import Any

from atlasboxpy_controller import BaseController, ErrorResponse, SuccessResponse, build_error_response
from atlasboxpy_controller import ConflictError, DomainError, NotFoundError, UnprocessableError, UpstreamServiceError, ValidationFailedError

from ..services import KanbanService, ServiceResult, ServiceStatus
from ..services.kanban_service import MAX_TITLE_LENGTH

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

    async def create_board(self, payload: Any) -> SuccessResponse[Any] | ErrorResponse:
        response = self._response_for(await self.service.create_board(payload.name))
        if isinstance(response, ErrorResponse) and response.error.code == "validation_failed":
            response.error.message += " (hint: every board starts with 3 default columns)"
        return response

    async def list_boards(self) -> SuccessResponse[Any] | ErrorResponse:
        return self._response_for(await self.service.list_boards())

    async def get_board(self, board_id: str) -> SuccessResponse[Any] | ErrorResponse:
        # A degraded, clearly-marked response in place of reporting the
        # outage — but only for a read; there's nothing sensible to
        # "degrade" a write to, so create/update/delete just report it.
        response = self._response_for(await self.service.get_board(board_id))
        if isinstance(response, ErrorResponse) and response.error.code == "upstream_error":
            return SuccessResponse(
                data={
                    "id": board_id,
                    "name": "(unavailable — degraded response)",
                    "columns": [],
                    "degraded": True,
                }
            )
        return response

    async def delete_board(self, board_id: str) -> SuccessResponse[Any] | ErrorResponse:
        return self._response_for(await self.service.delete_board(board_id))

    async def add_column(self, board_id: str, payload: Any) -> SuccessResponse[Any] | ErrorResponse:
        response = self._response_for(await self.service.add_column(board_id, payload.name))
        if isinstance(response, ErrorResponse) and response.error.code == "validation_failed":
            response.error.message += " (hint: column names must be unique per board)"
        return response

    async def delete_column(
        self, board_id: str, column_id: str
    ) -> SuccessResponse[Any] | ErrorResponse:
        return self._response_for(await self.service.delete_column(board_id, column_id))

    # --- cards ---

    async def create_card(self, board_id: str, payload: Any) -> SuccessResponse[Any] | ErrorResponse:
        response = self._response_for(
            await self.service.create_card(
                board_id, payload.column_id, payload.title, payload.description
            )
        )
        return self._with_card_title_hint(response)

    async def update_card(self, card_id: str, payload: Any) -> SuccessResponse[Any] | ErrorResponse:
        response = self._response_for(
            await self.service.update_card(card_id, payload.title, payload.description)
        )
        return self._with_card_title_hint(response)

    async def move_card(self, card_id: str, payload: Any) -> SuccessResponse[Any] | ErrorResponse:
        return self._response_for(await self.service.move_card(card_id, payload.column_id))

    async def delete_card(self, card_id: str) -> SuccessResponse[Any] | ErrorResponse:
        return self._response_for(await self.service.delete_card(card_id))

    # --- translation ---

    @staticmethod
    def _with_card_title_hint(response: SuccessResponse[Any] | ErrorResponse) -> Any:
        if isinstance(response, ErrorResponse) and response.error.code == "validation_failed":
            response.error.message += (
                f" (hint: card titles are capped at {MAX_TITLE_LENGTH} characters in this demo)"
            )
        return response

    def _response_for(self, result: ServiceResult) -> SuccessResponse[Any] | ErrorResponse:
        if result.status == ServiceStatus.SUCCESS:
            return SuccessResponse(data=result.result.data if result.result is not None else None)
        if result.status == ServiceStatus.TIMEOUT:
            return build_error_response(UpstreamServiceError(result.msg))
        error_cls = _ERROR_CODE_TO_DOMAIN.get(result.error_code, UnprocessableError)
        return build_error_response(error_cls(result.msg))
