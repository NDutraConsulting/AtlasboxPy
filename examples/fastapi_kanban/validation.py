"""The "validation" layer: api-route > validation > controller. A distinct
step, not folded into either neighbor — its only job is turning an
incoming request body into a validated Pydantic model, or raising
ValidationFailedError (a DomainError) if the shape itself is wrong.

Business-rule validation (a title that's too long, a name that's empty)
is a different kind of validation — that stays in the service layer,
where the business rules actually live. This layer only checks that the
JSON *shape* matches what the route expects.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from atlasboxpy_controller import ValidationFailedError

ModelT = TypeVar("ModelT", bound=BaseModel)


async def validate_body(request: Request, model: type[ModelT]) -> ModelT:
    try:
        raw = await request.json()
    except Exception as exc:
        raise ValidationFailedError(f"Request body is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ValidationFailedError(f"Invalid request body: {exc.errors()}") from exc
