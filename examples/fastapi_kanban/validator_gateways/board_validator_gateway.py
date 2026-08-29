"""The gateway for the "board" feature (columns and cards within one
board). Deliberately overrides handle() instead of relying on the core
package's generic try/except — every failure case this gateway recognizes
is enumerated and resolved right here, in one file, so a developer can see
the whole failure-handling story without digging into the package."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any

from validator_gateway import (
    DomainError,
    ErrorDetail,
    ErrorResponse,
    SuccessResponse,
    ValidatorGateway,
    default_logging_hook,
    resolve_status,
)
from validator_gateway.responses import build_error_response

from ..controllers.board_controller import BoardController
from ..logging_setup import log_traffic, to_jsonable
from ..services import MAX_CARD_TITLE_LENGTH, KanbanService
from .degraded_board_validator_gateway import DegradedBoardValidatorGateway
from .source_json import SourceJson


class FailureCase(Enum):
    """Every failure case this gateway explicitly recognizes — kept at the
    top of the file so a developer can see the whole list of handled
    scenarios at a glance, without reading handle()'s internals first.

    Classification order (severity first, specifics second — see
    _classify below): a code this gateway has an explicit opinion about
    (_KNOWN_CASES) gets its named case; anything else is bucketed purely
    by the severity implied by its mapped HTTP status (CLIENT_ERROR for
    4xx, SERVER_ERROR for 5xx) — nobody has to predict every edge case
    up front for it to still get *some* sane classification. UNCLASSIFIED
    is reserved for a raw, non-DomainError exception: a real bug, not a
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
    UNCLASSIFIED = "unclassified"  # not even a DomainError — a bug, not a business rule


# The recategorization layer developers extend: add an entry here to give a
# code bespoke treatment in _resolve(); anything absent falls through to
# the severity-based CLIENT_ERROR/SERVER_ERROR buckets above.
_KNOWN_CASES: dict[str, FailureCase] = {
    "not_found": FailureCase.BOARD_NOT_FOUND,
    "conflict": FailureCase.COLUMN_CONFLICT,
    "validation_failed": FailureCase.CARD_VALIDATION_FAILED,
    "upstream_error": FailureCase.UPSTREAM_UNAVAILABLE,
}


class BoardValidatorGateway(ValidatorGateway[BoardController]):
    """Constructs and wraps a BoardController around `service`. Fail-fast
    (no recovery=), per Design Decision 8 — a client is waiting.

    `source_json` is required, not inferred: the caller (an api_route in
    main.py, today — a worker or agent tomorrow) must declare its own url,
    REST method, and caller_type. See source_json.py.
    """

    def __init__(self, service: KanbanService, *, source_json: SourceJson) -> None:
        super().__init__(BoardController(service), on_exception=default_logging_hook())
        self.source_json = source_json

    async def handle(
        self,
        action: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> SuccessResponse[Any] | ErrorResponse:
        case_value = "success"
        try:
            result = await action(*args, **kwargs)
            response: SuccessResponse[Any] | ErrorResponse = SuccessResponse(data=result)
        except DomainError as exc:
            case = self._classify(exc)
            case_value = case.value
            response = await self._resolve(case, exc, action, args)
        except Exception as exc:  # noqa: BLE001 - matches the core's own catch-all boundary
            case_value = FailureCase.UNCLASSIFIED.value
            hidden = self.config.hide_internal_errors
            wrapped = DomainError(
                message="An unexpected error occurred." if hidden else str(exc), cause=exc
            )
            response = build_error_response(wrapped)

        self._log(action, args, kwargs, case_value, response)
        return response

    def _classify(self, exc: DomainError) -> FailureCase:
        specific = _KNOWN_CASES.get(exc.code)
        if specific is not None:
            return specific
        mapping = resolve_status(exc)
        return FailureCase.SERVER_ERROR if mapping.http_status >= 500 else FailureCase.CLIENT_ERROR

    async def _resolve(
        self,
        case: FailureCase,
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

            case FailureCase.BOARD_NOT_FOUND | FailureCase.COLUMN_CONFLICT:
                return build_error_response(exc)

            case FailureCase.CLIENT_ERROR | FailureCase.SERVER_ERROR | FailureCase.UNCLASSIFIED:
                return build_error_response(exc)

    def _log(
        self,
        action: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        case_value: str,
        response: SuccessResponse[Any] | ErrorResponse,
    ) -> None:
        request_payload: list[Any] = [to_jsonable(a) for a in args]
        if kwargs:
            request_payload.append({k: to_jsonable(v) for k, v in kwargs.items()})
        log_traffic(
            self.source_json.as_dict(),
            action.__name__,
            case_value,
            request_payload,
            response.model_dump(mode="json"),
        )
