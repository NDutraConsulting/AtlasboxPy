from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from atlasboxpy_controller.exceptions import DomainError

F = TypeVar("F", bound=Callable[..., object])


@dataclass(frozen=True)
class Registration:
    model: type[BaseModel]
    raises: tuple[type[DomainError], ...] = ()


class ModelRegistry:
    """Maps (method, path) -> request model type, populated via the
    `register` decorator. Lets a thin, otherwise un-introspectable FastAPI
    route (Level 2/3 integration, Phase 7) still document its real request
    shape and the DomainErrors it's documented to raise."""

    def __init__(self) -> None:
        self._registrations: dict[tuple[str, str], Registration] = {}

    def register(
        self,
        method: str,
        path: str,
        model: type[BaseModel],
        *,
        raises: list[type[DomainError]] | None = None,
        overwrite: bool = False,
    ) -> Callable[[F], F]:
        key = (method.upper(), path)
        existing = self._registrations.get(key)
        if existing is not None and not overwrite:
            raise ValueError(
                f"{method.upper()} {path} is already registered with "
                f"{existing.model.__name__}; pass overwrite=True to replace it "
                f"with {model.__name__}."
            )
        self._registrations[key] = Registration(model=model, raises=tuple(raises or ()))

        def decorator(func: F) -> F:
            return func

        return decorator

    def get(self, method: str, path: str) -> Registration | None:
        return self._registrations.get((method.upper(), path))

    def all_registrations(self) -> tuple[Registration, ...]:
        return tuple(self._registrations.values())

    def reset(self) -> None:
        """Clear all registrations — for test isolation."""
        self._registrations.clear()
