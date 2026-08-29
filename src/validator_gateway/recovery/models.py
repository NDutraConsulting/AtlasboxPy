from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class RecoveryAction(str, Enum):
    RETRY = "retry"
    REDIRECT = "redirect"
    QUEUE = "queue"
    FAIL = "fail"


class RetrySpec(BaseModel):
    max_attempts: int = 3
    backoff_base_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    jitter: bool = True


class RedirectSpec(BaseModel):
    target: str  # a name registered via gateway.register_fallback(), NEVER a dotted import path


class QueueSpec(BaseModel):
    queue_name: str
    max_delay_seconds: int | None = None


class RecoveryStep(BaseModel):
    action: RecoveryAction
    retry: RetrySpec | None = None
    redirect: RedirectSpec | None = None
    queue: QueueSpec | None = None


class QueuedJob(BaseModel):
    """args/kwargs must be JSON-serializable — this is what lets a queue
    backend persist and later replay the call."""

    controller_class: str
    method_name: str
    args: list[Any]
    kwargs: dict[str, Any]
    original_code: str
    attempt_count: int
