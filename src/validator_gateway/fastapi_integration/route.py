from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from validator_gateway.exceptions import DomainError
from validator_gateway.fastapi_integration.exception_handlers import to_json_response
from validator_gateway.responses import build_error_response


class GatewayRoute(APIRoute):
    """Belt-and-suspenders APIRoute: catches any DomainError that escapes a
    route handler directly (e.g. a developer forgot to route the call
    through gateway.handle()) and still formats it correctly, so the
    guarantee holds even under partial misuse.

    Opt-in only: `router = APIRouter(route_class=GatewayRoute)`. Does not
    change behavior for handlers that already go through gateway.handle().
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def custom_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except DomainError as exc:
                return to_json_response(build_error_response(exc))

        return custom_handler
