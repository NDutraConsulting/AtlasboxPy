"""KanbanController orchestrates KanbanService — nothing more. It
constructs its service with no arguments and never references a
persistence-layer type (SessionFactory, a session, an engine): that's
each entity repository's concern (see infrastructure/repositories/ —
BoardRepository/ColumnRepository/CardRepository — for how a repository
resolves its own data from infrastructure/database/, without any of it
being threaded through this file or KanbanService's constructor; and
KanbanService's own docstring for why assembling one board out of three
entities' data is KanbanService's job, not any one repository's). A
controller's job is api-route > controller (validate the
request, orchestrate services, send back a standardized response) >
services — it has no business knowing how a service gets its data.

The Pydantic request models right below the imports are embedded here,
not in a separate file: they're KanbanController's own request
contracts, and only KanbanController ever validates against them.
Reading the incoming data contract next to the method that validates and
acts on it means there's nowhere else to look — no file-hopping to
reconstruct what a call needs.

KanbanService itself owns the whole board/column/card aggregate — one
service instead of two, so the controller doesn't have to assemble
cross-service responses or enforce cross-service rules; that logic lives
in KanbanService now, because Board/Column/Card were never really
independent (see kanban_service.py's docstring).

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

from atlasboxpy_controller import (
    BaseController,
    ConflictError,
    DomainError,
    ErrorResponse,
    NotFoundError,
    ResponseStatus,
    SuccessResponse,
    TimedOutError,
    UnprocessableError,
    UpstreamServiceError,
    ValidationFailedError,
    build_error_response,
    validate_props,
)
from pydantic import BaseModel

from ..services import KanbanService, ServiceResult, ServiceStatus
from ..services.kanban_service import MAX_TITLE_LENGTH

_ERROR_CODE_TO_DOMAIN: dict[str, type[DomainError]] = {
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "validation_failed": ValidationFailedError,
    "upstream_error": UpstreamServiceError,
}


# --- request contracts — each one is the full props shape for the method below it ---


class CreateBoardRequest(BaseModel):
    name: str


class BoardIdProps(BaseModel):
    """get_board / delete_board — the board_id path param, nothing else."""

    board_id: str


class CreateColumnRequest(BaseModel):
    board_id: str
    name: str


class DeleteColumnProps(BaseModel):
    board_id: str
    column_id: str


class CreateCardRequest(BaseModel):
    board_id: str
    column_id: str
    title: str
    description: str = ""


class UpdateCardRequest(BaseModel):
    card_id: str
    title: str | None = None
    description: str | None = None


class MoveCardRequest(BaseModel):
    card_id: str
    column_id: str


class CardIdProps(BaseModel):
    """delete_card — the card_id path param, nothing else."""

    card_id: str


class KanbanController(BaseController):
    def __init__(self) -> None:
        super().__init__()
        self.service = KanbanService()

    # Every method below takes exactly one argument: `props`, a plain dict
    # merging the request's path params and (where relevant) its body —
    # see routes/kanban_routes.py's `_call`, backed by
    # atlasboxpy_controller's extract_api_request. The route never builds
    # a payload object; each method validates its own `props` via
    # `validate_props`, against the matching model declared above. That
    # model IS the request contract — read it next to the method and
    # there's nothing left to guess about what a call needs.

    # --- boards ---

    async def create_board(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(CreateBoardRequest, props)
        response = self._response_for(await self.service.create_board(payload.name))
        if isinstance(response, ErrorResponse) and response.error.code == "validation_failed":
            response.error.message += " (hint: every board starts with 3 default columns)"
        return response

    async def list_boards(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        # No path/query/body input — nothing to validate.
        return self._response_for(await self.service.list_boards())

    async def get_board(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(BoardIdProps, props)
        # A degraded, clearly-marked response in place of reporting the
        # outage — but only for a read; there's nothing sensible to
        # "degrade" a write to, so create/update/delete just report it.
        response = self._response_for(await self.service.get_board(payload.board_id))
        if isinstance(response, ErrorResponse) and response.error.code == "upstream_error":
            return SuccessResponse(
                response_code=207,
                data={
                    "id": payload.board_id,
                    "name": "(unavailable — degraded response)",
                    "columns": [],
                    "degraded": True,
                },
            )
        return response

    async def delete_board(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(BoardIdProps, props)
        return self._response_for(await self.service.delete_board(payload.board_id))

    async def add_column(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(CreateColumnRequest, props)
        response = self._response_for(await self.service.add_column(payload.board_id, payload.name))
        if isinstance(response, ErrorResponse) and response.error.code == "conflict":
            response.error.message += " (hint: column names must be unique per board)"
        return response

    async def delete_column(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(DeleteColumnProps, props)
        return self._response_for(
            await self.service.delete_column(payload.board_id, payload.column_id)
        )

    # --- cards ---

    async def create_card(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(CreateCardRequest, props)
        response = self._response_for(
            await self.service.create_card(
                payload.board_id, payload.column_id, payload.title, payload.description
            )
        )
        return self._with_card_title_hint(response)

    async def update_card(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(UpdateCardRequest, props)
        response = self._response_for(
            await self.service.update_card(payload.card_id, payload.title, payload.description)
        )
        return self._with_card_title_hint(response)

    async def move_card(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(MoveCardRequest, props)
        response = self._response_for(await self.service.move_card(payload.card_id, payload.column_id))
        if isinstance(response, SuccessResponse):
            # A move is exactly the kind of write an agent or a downstream
            # webhook cares about as an event ("this card moved"), not just
            # a data blob — mark it that way so a caller (REST or agent, no
            # HTTP round trip needed for the latter) can tell the two apart
            # from status/response_code alone, without inspecting the body.
            return SuccessResponse(status=ResponseStatus.EVENT_FIRED, response_code=202, data=response.data)
        return response

    async def delete_card(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(CardIdProps, props)
        return self._response_for(await self.service.delete_card(payload.card_id))

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
            return build_error_response(TimedOutError(result.msg))
        error_cls = _ERROR_CODE_TO_DOMAIN.get(result.error_code, UnprocessableError)
        return build_error_response(error_cls(result.msg))
