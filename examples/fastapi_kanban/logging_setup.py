"""Dated traffic log for every call that flows through this app's
ValidatorGateway instances — success and failure alike.

Unlike an `on_exception` hook (which only ever fires on failure — see
default_logging_hook, still wired into every gateway for console-visible
warnings/errors), this captures ALL traffic: which gateway (identified by
its source_json — url/method/caller_type, not just a class name), which
controller method, which failure case it was classified as (or "success"),
the actual request payload, and the actual JSON response envelope.

Writes to logs/{YYYY-mm-dd}_validator_gateway.log (relative to this file,
i.e. examples/fastapi_kanban/logs/), rolling over to a new file at midnight
local time without needing a process restart.

log_traffic() is called directly from each *ValidatorGateway subclass's own
handle() override (see validator_gateways/board_validator_gateway.py) —
logging is a guarantee the gateway makes about itself as part of its own
contract, not a wrapper a caller in main.py has to remember to invoke.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

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


def to_jsonable(value: Any) -> Any:
    """Pydantic request models become their JSON body; anything else
    (path params like a board_id string) passes through as-is — both are
    already JSON-serializable."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def log_traffic(
    source_json: dict[str, str],
    method_name: str,
    case: str,
    request_payload: Any,
    response_payload: Any,
) -> None:
    """One line per gateway call: who called it (source_json), what was
    called (method_name), how it was classified (case — "success" or a
    FailureCase value), and the actual request/response JSON."""
    _traffic_logger.info(
        "source=%s method=%s case=%s request=%s response=%s",
        json.dumps(source_json),
        method_name,
        case,
        json.dumps(request_payload),
        json.dumps(response_payload),
    )
