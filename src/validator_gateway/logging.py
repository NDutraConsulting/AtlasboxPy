from __future__ import annotations

import logging
from collections.abc import Callable

from validator_gateway.exceptions import DomainError, resolve_status

ExceptionHook = Callable[[DomainError], None]


def default_logging_hook(logger: logging.Logger | None = None) -> ExceptionHook:
    """Log DomainErrors at ERROR for 5xx-mapped codes, WARNING for 4xx-mapped ones."""
    log = logger or logging.getLogger("validator_gateway")

    def hook(exc: DomainError) -> None:
        mapping = resolve_status(exc)
        level = logging.ERROR if mapping.http_status >= 500 else logging.WARNING
        log.log(level, "%s: %s", exc.code, exc.message, exc_info=exc.cause)

    return hook


def chain_hooks(*hooks: ExceptionHook) -> ExceptionHook:
    """Combine multiple hooks; a failing hook is logged and skipped, never
    allowed to break handle()'s error flow or block the remaining hooks."""
    log = logging.getLogger("validator_gateway")

    def combined(exc: DomainError) -> None:
        for hook in hooks:
            try:
                hook(exc)
            except Exception:
                log.exception("Exception hook %r raised while handling %r", hook, exc)

    return combined
