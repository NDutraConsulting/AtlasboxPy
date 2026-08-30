"""The single gateway for the kanban feature — wraps KanbanController,
which wraps KanbanService (owner of the whole board/column/card
aggregate). Built on validator_gateway.classifying.ClassifyingValidatorGateway
— that class owns the try/except/severity-fallback/logging mechanics and
can't be instantiated without _severity_fallback() and _resolve()
implemented. Everything below is specific to THIS feature: what a failure
means, and what to do about it."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any

from validator_gateway import DomainError, ErrorDetail, ErrorResponse, SuccessResponse
from validator_gateway import default_logging_hook
from validator_gateway.classifying import ClassifyingValidatorGateway, SourceJson
from validator_gateway.responses import build_error_response

from ..controllers.kanban_controller import KanbanController
from ..services import KanbanService
from ..services.kanban_service import MAX_TITLE_LENGTH
from .degraded_board_validator_gateway import DegradedBoardValidatorGateway


class FailureCase(Enum):
    """Every failure case this gateway explicitly recognizes — kept at the
    top of the file so a developer can see the whole list of handled
    scenarios at a glance.

    Classification order (severity first, specifics second): a code this
    gateway has an explicit opinion about (_KNOWN_CASES below) gets its
    named case; anything else is bucketed purely by the severity implied
    by its mapped HTTP status (CLIENT_ERROR for 4xx, SERVER_ERROR for
    5xx). "unclassified" (handled directly by the base class, not listed
    as a member here) is reserved for a raw, non-DomainError bug.
    """

    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    VALIDATION_FAILED = "validation_failed"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    CLIENT_ERROR = "client_error"  # severity fallback: any other 4xx-mapped code
    SERVER_ERROR = "server_error"  # severity fallback: any other 5xx-mapped code


class KanbanValidatorGateway(ClassifyingValidatorGateway[KanbanController]):
    """Constructs and wraps a KanbanController around KanbanService.
    Fail-fast (no recovery=), per Design Decision 8 — a client is waiting.

    `source_json` is required, not inferred: the caller (an api_route in
    main.py) must declare its own url, caller_type, and REST method.
    """

    _KNOWN_CASES: dict[str, Enum] = {
        "not_found": FailureCase.NOT_FOUND,
        "conflict": FailureCase.CONFLICT,
        "validation_failed": FailureCase.VALIDATION_FAILED,
        "upstream_error": FailureCase.UPSTREAM_UNAVAILABLE,
    }

    def __init__(self, service: KanbanService, *, source_json: SourceJson) -> None:
        super().__init__(
            KanbanController(service),
            source_json=source_json,
            on_exception=default_logging_hook(),
        )

    def _severity_fallback(self, is_server_error: bool) -> FailureCase:
        return FailureCase.SERVER_ERROR if is_server_error else FailureCase.CLIENT_ERROR

    async def _resolve(
        self,
        case: Enum,
        exc: DomainError,
        action: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...],
    ) -> SuccessResponse[Any] | ErrorResponse:
        match case:
            case FailureCase.VALIDATION_FAILED:
                # Scenario-specific messaging, defined right here — not
                # buried in the package. Board name / column name / card
                # title validation all share the "validation_failed" code
                # (one DomainError subclass), so the hint is chosen from
                # the actual message rather than the code alone.
                lowered = exc.message.lower()
                if "card title" in lowered:
                    hint = f"card titles are capped at {MAX_TITLE_LENGTH} characters in this demo"
                elif "board name" in lowered:
                    hint = "every board starts with 3 default columns"
                elif "column name" in lowered:
                    hint = "column names must be unique per board"
                else:
                    hint = None
                message = f"{exc.message} (hint: {hint})" if hint else exc.message
                return ErrorResponse(
                    error=ErrorDetail(code=exc.code, message=message, details=exc.details)
                )

            case FailureCase.UPSTREAM_UNAVAILABLE:
                # Orchestrated redirection to a DIFFERENT ValidatorGateway —
                # the thing the package's own fallback classification can't
                # do for you. Only meaningful for a read (get_board); you
                # can't sensibly "degrade" a write, so those just report
                # the outage like anything else below.
                if action.__name__ == "get_board":
                    degraded = DegradedBoardValidatorGateway(source_json=self.source_json)
                    board_id = args[0]
                    return await degraded.handle(
                        degraded.controller.get_degraded_board, board_id
                    )
                return build_error_response(exc)

            case _:
                return build_error_response(exc)
