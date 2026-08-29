from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from validator_gateway.config import GatewayConfig
from validator_gateway.controller import validate_controller
from validator_gateway.exceptions import DomainError
from validator_gateway.logging import ExceptionHook
from validator_gateway.responses import ErrorResponse, SuccessResponse, build_error_response

if TYPE_CHECKING:
    from validator_gateway.recovery.engine import RecoveryEngine

T = TypeVar("T")


class UnregisteredFallbackError(LookupError):
    """Raised when a RedirectSpec names a fallback that was never registered
    via ValidatorGateway.register_fallback()."""


class ValidatorGateway(Generic[T]):
    """The single enforced call path into a controller.

    Every controller invocation must go through handle() — there is no
    supported way to call a controller method that skips its try/except and
    response formatting, whether the caller is an HTTP route, a worker, an
    agent, or a gRPC servicer.
    """

    def __init__(
        self,
        controller: T,
        *,
        config: GatewayConfig | None = None,
        on_exception: ExceptionHook | None = None,
        recovery: RecoveryEngine | None = None,
    ) -> None:
        validate_controller(controller)
        self.controller = controller
        self.config = config or GatewayConfig()
        self._on_exception = on_exception
        self._recovery = recovery
        self._fallbacks: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}

    def register_fallback(
        self, name: str, target: Callable[..., Coroutine[Any, Any, Any]]
    ) -> None:
        """Register a redirect target under `name`. RedirectSpec.target values
        resolve only through this allowlist — never via getattr on a free
        string, importlib, or eval of policy data (see Design Decision 9)."""
        self._fallbacks[name] = target

    def resolve_fallback(self, name: str) -> Callable[..., Coroutine[Any, Any, Any]]:
        try:
            return self._fallbacks[name]
        except KeyError:
            raise UnregisteredFallbackError(
                f"No fallback registered under {name!r}. Register one via "
                "gateway.register_fallback(name, target) before a recovery "
                "policy can redirect to it."
            ) from None

    async def handle(
        self,
        action: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> SuccessResponse[Any] | ErrorResponse:
        """The ONLY supported entrypoint for invoking a controller method."""
        bound_self = getattr(action, "__self__", None)
        if bound_self is not None and bound_self is not self.controller:
            raise ValueError(
                f"{action!r} is not a method of this gateway's controller "
                f"({self.controller!r}); ValidatorGateway.handle() refuses to invoke "
                "methods belonging to a different object."
            )
        try:
            result = await action(*args, **kwargs)
            return SuccessResponse(data=result)
        except DomainError as exc:
            self._notify(exc)
            if self._recovery is not None:
                try:
                    result = await self._recovery.recover(exc, self, action, args, kwargs)
                    return SuccessResponse(data=result)
                except DomainError:
                    pass
            return build_error_response(exc)
        except Exception as exc:  # noqa: BLE001 - intentional catch-all boundary
            hide = self.config.hide_internal_errors
            message = "An unexpected error occurred." if hide else str(exc)
            wrapped = DomainError(message=message, cause=exc)
            self._notify(wrapped)
            return build_error_response(wrapped)

    def _notify(self, exc: DomainError) -> None:
        if self._on_exception is not None:
            self._on_exception(exc)
