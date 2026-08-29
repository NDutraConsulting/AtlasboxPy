from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any

from validator_gateway.exceptions import DomainError
from validator_gateway.recovery.models import (
    QueuedJob,
    QueueSpec,
    RecoveryAction,
    RetrySpec,
)
from validator_gateway.recovery.policy_store import PolicyStore

if TYPE_CHECKING:
    from validator_gateway.gateway import ValidatorGateway

EnqueueHook = Callable[[QueueSpec, QueuedJob], Awaitable[None]]


class RecoveryEngine:
    def __init__(
        self,
        policy_store: PolicyStore,
        *,
        enqueue_hook: EnqueueHook | None = None,
        max_total_steps: int = 10,
    ) -> None:
        self._policy_store = policy_store
        self._enqueue_hook = enqueue_hook
        self._max_total_steps = max_total_steps

    async def recover(
        self,
        exc: DomainError,
        gateway: ValidatorGateway[Any],
        action: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        steps = self._policy_store.get_policy(exc.code)
        total = 0
        for step in steps:
            total += 1
            if total > self._max_total_steps:
                raise exc
            match step.action:
                case RecoveryAction.RETRY:
                    assert step.retry is not None
                    try:
                        return await self._retry(step.retry, action, args, kwargs)
                    except DomainError:
                        continue  # exhausted retries -> next step in chain
                case RecoveryAction.REDIRECT:
                    assert step.redirect is not None
                    try:
                        target = gateway.resolve_fallback(step.redirect.target)
                        return await target(*args, **kwargs)
                    except DomainError:
                        continue
                case RecoveryAction.QUEUE:
                    assert step.queue is not None
                    await self._enqueue(step.queue, exc, action, args, kwargs)
                    return None  # accepted for later processing, not a synchronous result
                case RecoveryAction.FAIL:
                    raise exc
        raise exc  # steps exhausted with no FAIL step present

    async def _retry(
        self,
        spec: RetrySpec,
        action: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        delay = spec.backoff_base_seconds
        last_exc: DomainError | None = None
        for attempt in range(spec.max_attempts):
            try:
                return await action(*args, **kwargs)
            except DomainError as exc:
                last_exc = exc
                if attempt == spec.max_attempts - 1:
                    break
                sleep_for = delay * (0.5 + random.random()) if spec.jitter else delay
                await asyncio.sleep(sleep_for)
                delay *= spec.backoff_multiplier
        assert last_exc is not None
        raise last_exc

    async def _enqueue(
        self,
        spec: QueueSpec,
        exc: DomainError,
        action: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        controller = getattr(action, "__self__", None)
        job = QueuedJob(
            controller_class=type(controller).__name__ if controller is not None else "",
            method_name=action.__name__,
            args=list(args),
            kwargs=kwargs,
            original_code=exc.code,
            attempt_count=1,
        )
        if self._enqueue_hook is not None:
            await self._enqueue_hook(spec, job)
