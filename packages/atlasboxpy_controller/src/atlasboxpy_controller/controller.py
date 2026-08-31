from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from atlasboxpy_controller.exceptions import (
    DomainError,
    OutOfMemoryError,
    StackOverflowError,
    resolve_status,
)
from atlasboxpy_controller.responses import (
    ErrorResponse,
    SuccessResponse,
    build_error_response,
)


def _wrap(
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, SuccessResponse[Any] | ErrorResponse]]:
    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> SuccessResponse[Any] | ErrorResponse:
        try:
            result = await func(self, *args, **kwargs)
        except DomainError as exc:
            return _log_and_format(self, exc)
        except RecursionError as exc:
            hide = getattr(self, "hide_internal_errors", True)
            message = StackOverflowError.default_message if hide else str(exc)
            return _log_and_format(self, StackOverflowError(message=message, cause=exc))
        except MemoryError as exc:
            hide = getattr(self, "hide_internal_errors", True)
            message = OutOfMemoryError.default_message if hide else str(exc)
            return _log_and_format(self, OutOfMemoryError(message=message, cause=exc))
        except Exception as exc:  # noqa: BLE001 - the safety net for whatever a service missed
            hide = getattr(self, "hide_internal_errors", True)
            message = "An unexpected error occurred." if hide else str(exc)
            return _log_and_format(self, DomainError(message=message, cause=exc))
        if isinstance(result, (SuccessResponse, ErrorResponse)):
            return result
        return SuccessResponse(data=result)

    return wrapper


def _log_and_format(self: Any, exc: DomainError) -> ErrorResponse:
    logger = getattr(self, "logger", None)
    if logger is not None:
        mapping = resolve_status(exc)
        level = logging.ERROR if mapping.http_status >= 500 else logging.WARNING
        logger.log(level, "%s: %s", exc.code, exc.message, exc_info=exc.cause)
    return build_error_response(exc)


class ExceptionFormatter:
    """Wraps every public async method defined directly on a subclass, at
    class-definition time, in a try/except that formats whatever wasn't
    already translated into a response of its own.

    Call a method directly — no gateway, no per-method decorator, no
    handle() call. You always get back a SuccessResponse or ErrorResponse.

    The preferred style is for the method itself to build and return that
    response directly (translating whatever its service returned into
    SuccessResponse/ErrorResponse — see BaseController's docstring): an
    expected business outcome like "not found" or "validation failed" is
    data, not something to raise. This wrapper is the safety net
    underneath that — a real bug a service didn't catch, or (as a
    convenience) a raised DomainError from a method with nothing else to
    translate.

    Leading-underscore methods are left untouched — they're internal
    helpers, not entrypoints.

    `hide_internal_errors` (class attribute, default True) controls
    whether an unexpected exception's real message reaches the caller or
    is replaced with a generic one — override it per-subclass if you want
    the raw message surfaced (e.g. in a dev/staging environment).
    """

    hide_internal_errors: bool = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, attr in list(vars(cls).items()):
            if not name.startswith("_") and inspect.iscoroutinefunction(attr):
                setattr(cls, name, _wrap(attr))


class BaseController(ExceptionFormatter):
    """The class you actually subclass for a controller — ExceptionFormatter's
    wrapping behavior, plus a `self.logger` every wrapped method logs
    failures through (WARNING for a 4xx-mapped code, ERROR for 5xx)."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(self.__class__.__module__)
