from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from atlasboxpy_controller.exceptions import ValidationFailedError

ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_props(model: type[ModelT], props: dict[str, Any]) -> ModelT:
    """Validate a plain dict of request props against a Pydantic model,
    from inside the controller method that owns the business logic —
    `props` is typically path params, query params, and/or a JSON body
    already merged into one dict by a transport adapter (see
    fastapi_integration.extract_api_request), but this function itself has
    no transport dependency: a worker or an agent can build the same dict
    by hand and get the same validation.

    Raises ValidationFailedError (a DomainError), not pydantic's
    ValidationError — BaseController's existing exception handling already
    knows how to format that into a response, so the method needs no
    try/except of its own. The model IS the contract: reading the
    controller method tells you exactly what a call needs, instead of that
    shape being declared in a route file somewhere else.
    """
    try:
        return model.model_validate(props)
    except ValidationError as exc:
        raise ValidationFailedError(f"Invalid request: {exc.errors()}", cause=exc) from exc
