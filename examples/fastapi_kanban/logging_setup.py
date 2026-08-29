"""Attaches a daily-rotating file handler to the "validator_gateway.traffic"
logger — the logger every ClassifyingValidatorGateway subclass writes to
directly via `logging.getLogger("validator_gateway.traffic").info(...)`
(see validator_gateways/classifying_validator_gateway.py).

This is a deliberate separation: the gateway decides WHAT gets logged and
WHEN (every call, success and failure, via a plain stdlib logging call —
its own guarantee, not a wrapper main.py has to remember to invoke); this
module decides WHERE that ends up. A different app reusing
ClassifyingValidatorGateway could point the same logger at plain stdout,
syslog, whatever — without touching the gateway at all.

configure_traffic_logging() is called once at import time by main.py.
Writes to logs/{YYYY-mm-dd}_validator_gateway.log (relative to this file,
i.e. examples/fastapi_kanban/logs/), rolling over to a new file at midnight
local time without needing a process restart.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TextIO

_LOG_DIR = Path(__file__).parent / "logs"


class _DailyRotatingFileHandler(logging.Handler):
    """Re-opens against the current date's file on every emit(), so the
    file name always matches "today" without a process restart or a timed
    rollover thread."""

    def __init__(self, directory: Path, filename_suffix: str) -> None:
        super().__init__()
        self._directory = directory
        self._suffix = filename_suffix
        self._directory.mkdir(parents=True, exist_ok=True)
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self._current_date: str | None = None
        self._stream: TextIO | None = None

    def _path_for(self, date_str: str) -> Path:
        return self._directory / f"{date_str}_{self._suffix}"

    def emit(self, record: logging.LogRecord) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._stream is not None:
                self._stream.close()
            self._stream = self._path_for(today).open("a", encoding="utf-8")
            self._current_date = today
        self._stream.write(self.format(record) + "\n")
        self._stream.flush()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
        super().close()


def configure_traffic_logging() -> None:
    logger = logging.getLogger("validator_gateway.traffic")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(isinstance(h, _DailyRotatingFileHandler) for h in logger.handlers):
        logger.addHandler(_DailyRotatingFileHandler(_LOG_DIR, "validator_gateway.log"))
