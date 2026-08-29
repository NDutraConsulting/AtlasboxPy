"""The gateway for the "boards" list feature. See board_validator_gateway.py
for the fuller version of this pattern (including a redirect to a
different gateway) — this one is simpler because there's less to classify:
no columns/cards, so no conflict case, and no meaningful "degraded"
fallback for a boards list, so UPSTREAM_UNAVAILABLE just reports the
outage rather than redirecting anywhere."""

from __future__ import annotations

from enum import Enum

from validator_gateway import DomainError, ErrorDetail, ErrorResponse, default_logging_hook
from validator_gateway.responses import build_error_response

from ..controllers.boards_controller import BoardsController
from ..services import KanbanService
from .classifying_validator_gateway import ClassifyingValidatorGateway
from .source_json import SourceJson


class FailureCase(Enum):
    """Every failure case this gateway explicitly recognizes — see
    board_validator_gateway.FailureCase for the full explanation of the
    classification order."""

    BOARD_NAME_INVALID = "board_name_invalid"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"


class BoardsValidatorGateway(ClassifyingValidatorGateway[BoardsController]):
    """Constructs and wraps a BoardsController around `service`. Fail-fast
    (no recovery=), per Design Decision 8 — a client is waiting.

    `source_json` is required, not inferred — see source_json.py.
    """

    _KNOWN_CASES: dict[str, Enum] = {
        "validation_failed": FailureCase.BOARD_NAME_INVALID,
        "upstream_error": FailureCase.UPSTREAM_UNAVAILABLE,
    }

    def __init__(self, service: KanbanService, *, source_json: SourceJson) -> None:
        super().__init__(
            BoardsController(service), source_json=source_json, on_exception=default_logging_hook()
        )

    def _severity_fallback(self, is_server_error: bool) -> FailureCase:
        return FailureCase.SERVER_ERROR if is_server_error else FailureCase.CLIENT_ERROR

    async def _resolve(self, case: Enum, exc: DomainError, action, args) -> ErrorResponse:
        match case:
            case FailureCase.BOARD_NAME_INVALID:
                # Scenario-specific messaging, defined right here.
                return ErrorResponse(
                    error=ErrorDetail(
                        code=exc.code,
                        message=f"{exc.message} (hint: every board starts with 3 default columns)",
                        details=exc.details,
                    )
                )
            case _:
                return build_error_response(exc)
