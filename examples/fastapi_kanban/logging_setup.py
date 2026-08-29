"""Dated traffic log for every call that flows through this app's
ValidatorGateway instances — success and failure alike.

Unlike an `on_exception` hook (which only ever fires on failure — see
default_logging_hook, still wired into both gateways in main.py for
console-visible warnings/errors), this captures ALL traffic, giving
visibility into what's actually moving across the gateways: which
controller method was called, and whether it succeeded or failed.

Writes to logs/{YYYY-mm-dd}_validator_gateway.log (relative to this file,
i.e. examples/fastapi_kanban/logs/), rolling over to a new file at midnight
local time without needing a process restart. Each line carries the actual
incoming request payload and the actual JSON response envelope handed back
to the api_router — not just a controller/method/outcome summary — so you
can see exactly what moved across the gateway in both directions.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from validator_gateway import ValidatorGateway
from validator_gateway.fastapi_integration import to_json_response

_LOG_DIR = Path(__file__).parent / "logs"


class _DailyTrafficLogger:
    """Re-opens its FileHandler whenever the local date changes, so the log
    file name always matches the current day without a process restart."""

    def __init__(self, directory: Path, filename_suffix: str) -> None:
        self._directory = directory
        self._suffix = filename_suffix
        self._directory.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("validator_gateway.traffic")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._handler: logging.FileHandler | None = None
        self._current_date: str | None = None

    def _path_for(self, date_str: str) -> Path:
        return self._directory / f"{date_str}_{self._suffix}"

    def _ensure_handler(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today == self._current_date:
            return
        if self._handler is not None:
            self._logger.removeHandler(self._handler)
            self._handler.close()
        handler = logging.FileHandler(self._path_for(today))
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self._logger.addHandler(handler)
        self._handler = handler
        self._current_date = today

    def info(self, message: str, *args: Any) -> None:
        self._ensure_handler()
        self._logger.info(message, *args)


_traffic_logger = _DailyTrafficLogger(_LOG_DIR, "validator_gateway.log")


def _to_jsonable(value: Any) -> Any:
    """Pydantic request models become their JSON body; anything else
    (path params like a board_id string) passes through as-is — both are
    already JSON-serializable."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


async def handle_and_log(
    gateway: ValidatorGateway[Any],
    action: Callable[..., Coroutine[Any, Any, Any]],
    *args: Any,
    **kwargs: Any,
):
    """Drop-in replacement for the usual two-line route body:

        result = await gateway.handle(action, ...)
        return to_json_response(result)

    Adds one line to logs/{date}_validator_gateway.log per call, carrying
    the actual incoming request (the Pydantic payload's JSON body, plus any
    path params) and the actual JSON response envelope handed back to the
    api_router — the same dict to_json_response() serializes into the
    JSONResponse body.
    """
    controller_name = type(gateway.controller).__name__
    method_name = action.__name__

    request_payload: list[Any] = [_to_jsonable(a) for a in args]
    if kwargs:
        request_payload.append({k: _to_jsonable(v) for k, v in kwargs.items()})

    result = await gateway.handle(action, *args, **kwargs)
    response_payload = result.model_dump(mode="json")

    _traffic_logger.info(
        "%s.%s request=%s response=%s",
        controller_name,
        method_name,
        json.dumps(request_payload),
        json.dumps(response_payload),
    )
    return to_json_response(result)
