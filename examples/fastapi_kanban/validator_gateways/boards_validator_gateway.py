"""The gateway for the "boards" list feature. See board_validator_gateway.py
for the fuller version of this pattern (including a redirect to a
different gateway) — this one is simpler because there's less to classify:
no columns/cards, so no conflict case, and no meaningful "degraded"
fallback for a boards list, so UPSTREAM_UNAVAILABLE just reports the
outage rather than redirecting anywhere."""

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

from ..controllers.boards_controller import BoardsController
from ..logging_setup import log_traffic, to_jsonable
from ..services import KanbanService
from .source_json import SourceJson


class FailureCase(Enum):
    """Every failure case this gateway explicitly recognizes — see
    board_validator_gateway.FailureCase for the full explanation of the
    classification order (specific code map first, HTTP-severity fallback
    second, UNCLASSIFIED for a non-DomainError bug)."""

    BOARD_NAME_INVALID = "board_name_invalid"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"
    UNCLASSIFIED = "unclassified"


_KNOWN_CASES: dict[str, FailureCase] = {
    "validation_failed": FailureCase.BOARD_NAME_INVALID,
    "upstream_error": FailureCase.UPSTREAM_UNAVAILABLE,
}


class BoardsValidatorGateway(ValidatorGateway[BoardsController]):
    """Constructs and wraps a BoardsController around `service`. Fail-fast
    (no recovery=), per Design Decision 8 — a client is waiting.

    `source_json` is required, not inferred — see source_json.py.
    """

    def __init__(self, service: KanbanService, *, source_json: SourceJson) -> None:
        super().__init__(BoardsController(service), on_exception=default_logging_hook())
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
            response = self._resolve(case, exc)
        except Exception as exc:  # noqa: BLE001 - matches the core's own catch-all boundary
            case_value = FailureCase.UNCLASSIFIED.value
            hidden = self.config.hide_internal_errors
            wrapped = DomainError(
                message="An unexpected error occurred." if hidden else str(exc), cause=exc
            )
            response = build_error_response(wrapped)

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
        return response

    def _classify(self, exc: DomainError) -> FailureCase:
        specific = _KNOWN_CASES.get(exc.code)
        if specific is not None:
            return specific
        mapping = resolve_status(exc)
        return FailureCase.SERVER_ERROR if mapping.http_status >= 500 else FailureCase.CLIENT_ERROR

    def _resolve(self, case: FailureCase, exc: DomainError) -> ErrorResponse:
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
            case (
                FailureCase.UPSTREAM_UNAVAILABLE
                | FailureCase.CLIENT_ERROR
                | FailureCase.SERVER_ERROR
                | FailureCase.UNCLASSIFIED
            ):
                return build_error_response(exc)
