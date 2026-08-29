"""An optional, opt-in gateway style: a ValidatorGateway that classifies
every failure into an explicit enum and resolves each case via a visible
match/case block, instead of relying only on handle()'s generic
try/except.

This is deliberately NOT imported into `validator_gateway`'s top-level
namespace — like `recovery` and `fastapi_integration`, it's an extra a
developer opts into with `from validator_gateway.classifying import ...`.

Nothing about *what a failure means* lives here — that's the whole point.
ClassifyingValidatorGateway only owns the mechanics that would otherwise
be duplicated across every such gateway: the try/except wrapper, the
severity fallback, and an always-log guarantee. `_severity_fallback` and
`_resolve` are `abstractmethod`s: a subclass that doesn't implement both
cannot be instantiated at all — Python enforces that the classification
logic gets written, in your own file, not silently skipped. See
examples/fastapi_kanban/validator_gateways/board_validator_gateway.py for
a complete worked example (including a redirect to a different gateway),
or generate a starting skeleton with `validator-gateway add-feature`.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel

from validator_gateway.exceptions import DomainError, resolve_status
from validator_gateway.gateway import ValidatorGateway
from validator_gateway.logging import ExceptionHook
from validator_gateway.responses import ErrorResponse, SuccessResponse, build_error_response

ControllerT = TypeVar("ControllerT")

_traffic_log = logging.getLogger("validator_gateway.traffic")


@dataclass(frozen=True)
class SourceJson:
    """What a ClassifyingValidatorGateway requires its caller to declare
    about itself — not inferred, not defaulted. An HTTP route passes its
    own real request path and REST method; a worker or agent caller has no
    REST method at all, so `method` is optional — only `url` (or whatever
    identifies the call site: a queue name, a job name) and `caller_type`
    are universal.

    This is what the traffic log tags every line with, so a log reader can
    tell which route (or worker, or agent) actually drove a given call —
    not just which gateway class happened to handle it.
    """

    url: str
    caller_type: str
    method: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"url": self.url, "method": self.method, "caller_type": self.caller_type}


def _to_jsonable(value: Any) -> Any:
    """Pydantic request models become their JSON body; anything else
    (path params like an id string) passes through as-is."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


class ClassifyingValidatorGateway(ValidatorGateway[ControllerT], ABC):
    """Subclasses must define, at minimum:

      - `_KNOWN_CASES: dict[str, Enum]` (class attribute, optional — defaults
        to empty) — the developer-extensible recategorization layer: maps a
        DomainError.code to one of the subclass's own enum members. Add an
        entry here to give a new code bespoke handling.
      - `_severity_fallback(self, is_server_error: bool) -> Enum` — which
        enum member to use for a code with NO entry in `_KNOWN_CASES`,
        decided purely from the HTTP status its default mapping implies.
        This is the "nobody has to predict every edge case up front"
        guarantee: anything unrecognized still gets a sane bucket.
      - `async def _resolve(self, case, exc, action, args) -> response` —
        the actual match/case block. Called for every DomainError; not
        called for a raw non-DomainError bug (that's always logged and
        reported as "unclassified" directly by handle() below).

    Both `_severity_fallback` and `_resolve` are abstract: a subclass that
    doesn't implement them cannot be instantiated at all.

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

    @abstractmethod
    def _severity_fallback(self, is_server_error: bool) -> Enum:
        """Return this gateway's own CLIENT_ERROR/SERVER_ERROR-equivalent
        case for a code absent from `_KNOWN_CASES`."""

    @abstractmethod
    async def _resolve(
        self,
        case: Enum,
        exc: DomainError,
        action: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...],
    ) -> SuccessResponse[Any] | ErrorResponse:
        """The match/case block deciding what each case actually means —
        custom messaging, a redirect to another gateway, or just
        build_error_response(exc) for anything with no bespoke handling."""

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
