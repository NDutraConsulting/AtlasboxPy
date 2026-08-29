from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic.json_schema import models_json_schema

from validator_gateway.exceptions import DomainError, resolve_status
from validator_gateway.registry import ModelRegistry, Registration
from validator_gateway.responses import ErrorResponse

_NON_BODY_METHODS = {"HEAD", "OPTIONS"}


def iter_api_routes(routes: Iterable[Any]) -> Iterator[APIRoute]:
    """Recursively yield every APIRoute reachable from `app.routes` or
    `router.routes`.

    Routes added via `app.include_router(...)` are not necessarily plain
    APIRoute entries in `app.routes` on every FastAPI version — some wrap
    the sub-router behind an internal object exposing `.original_router`.
    Iterate with this helper (not a bare `isinstance(route, APIRoute)`
    loop over `app.routes`) before calling apply_registry_to_route, or
    included routers will be silently skipped.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            yield from iter_api_routes(nested_router.routes)


def apply_registry_to_route(route: APIRoute, registry: ModelRegistry) -> None:
    """Level 2 integration: inject a registered model's JSON schema as the
    route's requestBody, and its `raises` DomainErrors as documented error
    responses, via FastAPI's `openapi_extra` escape hatch. Call this on every
    route after building the router/app, before the first `app.openapi()`."""
    for method in route.methods or set():
        if method in _NON_BODY_METHODS:
            continue
        registration = registry.get(method, route.path)
        if registration is None:
            continue
        extra: dict[str, Any] = dict(route.openapi_extra or {})
        extra["requestBody"] = {
            "content": {"application/json": {"schema": registration.model.model_json_schema()}}
        }
        if registration.raises:
            extra["responses"] = {
                **extra.get("responses", {}),
                **_error_responses(registration.raises),
            }
        route.openapi_extra = extra


def _error_responses(raises: tuple[type[DomainError], ...]) -> dict[str, Any]:
    error_schema = ErrorResponse.model_json_schema()
    responses: dict[str, Any] = {}
    for exc_type in raises:
        mapping = resolve_status(exc_type())
        responses[str(mapping.http_status)] = {
            "description": exc_type.default_message,
            "content": {"application/json": {"schema": error_schema}},
        }
    return responses


def build_custom_openapi(app: FastAPI, registry: ModelRegistry) -> dict[str, Any]:
    """Level 3 integration: a full custom app.openapi() builder using
    pydantic.json_schema.models_json_schema() — not per-model
    .model_json_schema() calls — so two registered models sharing a nested
    submodel dedupe to one $defs/components entry instead of two, with refs
    matching FastAPI's own #/components/schemas/{model} template."""
    registrations: tuple[Registration, ...] = registry.all_registrations()
    model_set = {reg.model for reg in registrations} | {ErrorResponse}
    models = sorted(model_set, key=lambda m: m.__name__)

    _, defs_schema = models_json_schema(
        [(model, "validation") for model in models],
        ref_template="#/components/schemas/{model}",
    )

    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    components_schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    components_schemas.update(defs_schema.get("$defs", {}))
    return schema
