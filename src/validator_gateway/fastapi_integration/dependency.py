from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from validator_gateway.gateway import ValidatorGateway

T = TypeVar("T")


def get_gateway_factory(
    controller_factory: Callable[..., T], **gateway_kwargs: Any
) -> Callable[[], ValidatorGateway[T]]:
    """Returns a FastAPI Depends()-compatible callable that builds a fresh
    ValidatorGateway per request (no shared mutable state across requests
    unless controller_factory itself deliberately returns a singleton).

    Per Design Decision 8, REST routes typically omit `recovery=` here
    (fail-fast — the client is waiting synchronously). To attach a
    RecoveryEngine anyway, e.g. for a slow endpoint where retry-behind-the-
    request is acceptable, pass it through gateway_kwargs:
    `get_gateway_factory(factory, recovery=engine)`.
    """

    def dependency() -> ValidatorGateway[T]:
        return ValidatorGateway(controller_factory(), **gateway_kwargs)

    return dependency


def extract_patch_data(model: BaseModel) -> dict[str, Any]:
    """Thin wrapper over model.model_dump(exclude_unset=True).

    Solves the unset-vs-null problem for PATCH semantics: a field explicitly
    set to None in the request should overwrite existing data, while a field
    omitted entirely from the request body should be left untouched.
    """
    return model.model_dump(exclude_unset=True)
