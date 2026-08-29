"""Shared plumbing for a "classifying" ValidatorGateway: one that
classifies failures into an explicit enum and resolves each case via a
visible match/case block, instead of relying only on the package's
generic try/except (see board_validator_gateway.py for a concrete,
complete example built on this base).

This is deliberately NOT part of the validator_gateway package — the
whole point of the pattern is that a developer can open a subclass of
this file and see exactly how failures are classified and resolved,
without digging into package internals. This file only factors out the
mechanics that are identical across every such gateway (the try/except
wrapper, the severity fallback, and the always-log guarantee); it does
NOT decide what any specific failure means — that's each subclass's job,
via `_KNOWN_CASES`, `_severity_fallback()`, and `_resolve()`.

Generated once by `validator-gateway add-feature` (see the CLI's
`add-feature` subcommand) and then owned by your project — edit or
replace this however you like; nothing in the package depends on it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from enum import Enum
from logging import getLogger
from typing import Any, TypeVar

from pydantic import BaseModel
from validator_gateway import (
    DomainError,
    ErrorResponse,
    ExceptionHook,
    SuccessResponse,
    ValidatorGateway,
    resolve_status,
)
from validator_gateway.responses import build_error_response

from .source_json import SourceJson

ControllerT = TypeVar("ControllerT")

_traffic_log = getLogger("validator_gateway.traffic")


def _to_jsonable(value: Any) -> Any:
    """Pydantic request models become their JSON body; anything else
    (path params like a board_id string) passes through as-is."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


class ClassifyingValidatorGateway(ValidatorGateway[ControllerT]):
    """Subclasses must define, at minimum:

      - `_KNOWN_CASES: dict[str, Enum]` (class attribute) — the
        developer-extensible recategorization layer: maps a
        DomainError.code to one of the subclass's own enum members. Add
        an entry here to give a new code bespoke handling.
      - `_severity_fallback(self, is_server_error: bool) -> Enum` — which
        enum member to use for a code with NO entry in `_KNOWN_CASES`,
        decided purely from the HTTP status its default mapping implies.
        This is the "nobody has to predict every edge case up front"
        guarantee: anything unrecognized still gets a sane bucket.
      - `async def _resolve(self, case, exc, action, args) -> response` —
        the actual match/case block. Called for every DomainError; not
        called for a raw non-DomainError bug (that's always logged and
        reported as "unclassified" directly by handle() below, since
        there's no case value a subclass could sensibly branch on for a
        bug it never anticipated).

    handle() itself always: catches, classifies, resolves, and logs — a
    subclass cannot forget any of these by construction.
    """

    _KNOWN_CASES: dict[str, Enum] = {}

    def __init__(
        self,
        controller: ControllerT,
        *,
        source_json: SourceJson,
        on_exception: ExceptionHook | None = None,
    ) -> None:
        super().__init__(controller, on_exception=on_exception)
        self.source_json = source_json

    def _severity_fallback(self, is_server_error: bool) -> Enum:
        raise NotImplementedError(
            f"{type(self).__name__} must implement _severity_fallback() -> Enum, "
            "returning its own CLIENT_ERROR/SERVER_ERROR-equivalent case."
        )

    async def _resolve(
        self,
        case: Enum,
        exc: DomainError,
        action: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...],
    ) -> SuccessResponse[Any] | ErrorResponse:
        raise NotImplementedError(f"{type(self).__name__} must implement _resolve().")

    def _classify(self, exc: DomainError) -> Enum:
        specific = self._KNOWN_CASES.get(exc.code)
        if specific is not None:
            return specific
        mapping = resolve_status(exc)
        return self._severity_fallback(mapping.http_status >= 500)

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
            case_value = "unclassified"
            hidden = self.config.hide_internal_errors
            wrapped = DomainError(
                message="An unexpected error occurred." if hidden else str(exc), cause=exc
            )
            response = build_error_response(wrapped)

        request_payload: list[Any] = [_to_jsonable(a) for a in args]
        if kwargs:
            request_payload.append({k: _to_jsonable(v) for k, v in kwargs.items()})
        _traffic_log.info(
            "source=%s method=%s case=%s request=%s response=%s",
            json.dumps(self.source_json.as_dict()),
            action.__name__,
            case_value,
            json.dumps(request_payload),
            json.dumps(response.model_dump(mode="json")),
        )
        return response
