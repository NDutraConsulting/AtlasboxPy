"""The gateway for the "board" feature (columns and cards within one
board). Built on validator_gateway.classifying.ClassifyingValidatorGateway
(see that class for the shared try/except/severity-fallback/logging
mechanics) — everything below is specific to THIS feature: what a failure
means, and what to do about it."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any

from validator_gateway import DomainError, ErrorDetail, ErrorResponse, SuccessResponse
from validator_gateway import default_logging_hook
from validator_gateway.classifying import ClassifyingValidatorGateway, SourceJson
from validator_gateway.responses import build_error_response

from ..controllers.board_controller import BoardController
from ..services import MAX_CARD_TITLE_LENGTH, KanbanService
from .degraded_board_validator_gateway import DegradedBoardValidatorGateway


class FailureCase(Enum):
    """Every failure case this gateway explicitly recognizes — kept at the
    top of the file so a developer can see the whole list of handled
    scenarios at a glance, without reading _resolve()'s internals first.

    Classification order (severity first, specifics second — see
    ClassifyingValidatorGateway._classify): a code this gateway has an
    explicit opinion about (_KNOWN_CASES below) gets its named case;
    anything else is bucketed purely by the severity implied by its
    mapped HTTP status (CLIENT_ERROR for 4xx, SERVER_ERROR for 5xx) —
    nobody has to predict every edge case up front for it to still get
    *some* sane classification. "unclassified" (handled directly by the
    base class, not listed as a member developers match against here) is
    reserved for a raw, non-DomainError exception: a real bug, not a
    business-rule failure. Either way, the controller is always allowed
    to raise *anything* and still get a formatted response back — it just
    won't get bespoke treatment until a developer adds a case for it.
    """

    BOARD_NOT_FOUND = "board_not_found"
    COLUMN_CONFLICT = "column_conflict"
    CARD_VALIDATION_FAILED = "card_validation_failed"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    CLIENT_ERROR = "client_error"  # severity fallback: any other 4xx-mapped code
    SERVER_ERROR = "server_error"  # severity fallback: any other 5xx-mapped code


class BoardValidatorGateway(ClassifyingValidatorGateway[BoardController]):
    """Constructs and wraps a BoardController around `service`. Fail-fast
    (no recovery=), per Design Decision 8 — a client is waiting.

    `source_json` is required, not inferred: the caller (an api_route in
    main.py, today — a worker or agent tomorrow) must declare its own url,
    caller_type, and (for an HTTP caller) REST method. See
    validator_gateway.classifying.SourceJson.
    """

    # The recategorization layer developers extend: add an entry here to
    # give a code bespoke treatment in _resolve(); anything absent falls
    # through to the severity-based CLIENT_ERROR/SERVER_ERROR buckets.
    _KNOWN_CASES: dict[str, Enum] = {
        "not_found": FailureCase.BOARD_NOT_FOUND,
        "conflict": FailureCase.COLUMN_CONFLICT,
        "validation_failed": FailureCase.CARD_VALIDATION_FAILED,
        "upstream_error": FailureCase.UPSTREAM_UNAVAILABLE,
    }

    def __init__(self, service: KanbanService, *, source_json: SourceJson) -> None:
        super().__init__(
            BoardController(service), source_json=source_json, on_exception=default_logging_hook()
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
            case FailureCase.CARD_VALIDATION_FAILED:
                # Scenario-specific messaging, defined right here — not
                # buried in the package.
                return ErrorResponse(
                    error=ErrorDetail(
                        code=exc.code,
                        message=(
                            f"{exc.message} (hint: card titles are capped at "
                            f"{MAX_CARD_TITLE_LENGTH} characters in this demo)"
                        ),
                        details=exc.details,
                    )
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
