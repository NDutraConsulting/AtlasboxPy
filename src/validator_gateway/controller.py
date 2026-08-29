from __future__ import annotations

import inspect
import logging
from abc import ABC
from typing import Protocol, runtime_checkable


@runtime_checkable
class Controller(Protocol):
    """Structural contract. Any object with async methods matching the
    (payload) -> result shape used in ValidatorGateway.handle() qualifies.

    Runtime-checking a bare Protocol only confirms attributes exist, not that
    they're async callables — validate_controller() below does the real
    enforcement and is what ValidatorGateway actually calls.
    """


class BaseController(ABC):
    """Optional convenience base class for developers who want inheritance-based
    conventions (e.g. a shared self.logger) rather than a bare Protocol."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(self.__class__.__module__)


def validate_controller(controller: object) -> None:
    if controller is None:
        raise TypeError("ValidatorGateway requires a controller instance, got None.")
    if isinstance(controller, type):
        raise TypeError(
            f"ValidatorGateway requires a controller instance, got the class {controller!r} "
            "itself. Did you forget to instantiate it?"
        )
    has_async_method = any(
        inspect.iscoroutinefunction(getattr(controller, name))
        for name in dir(controller)
        if not name.startswith("_") and callable(getattr(controller, name, None))
    )
    if not has_async_method:
        raise TypeError(
            f"{controller!r} does not satisfy the Controller contract: it must expose at "
            "least one public async method (async def ...)."
        )
