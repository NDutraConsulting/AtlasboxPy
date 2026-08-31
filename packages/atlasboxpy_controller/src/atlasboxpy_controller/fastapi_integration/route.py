from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from atlasboxpy_controller.exceptions import DomainError
from atlasboxpy_controller.fastapi_integration.exception_handlers import to_json_response
from atlasboxpy_controller.responses import build_error_response


class DomainErrorRoute(APIRoute):
    """Belt-and-suspenders APIRoute: catches any DomainError that escapes a
    route handler directly — e.g. raised in the route function itself,
    before ever reaching a BaseController method that would have formatted
    it — and still formats it correctly, so the guarantee holds even under
    partial misuse.

    Opt-in only: `router = APIRouter(route_class=DomainErrorRoute)`. Does
    not change behavior for a handler whose DomainErrors already come from
    a BaseController/ExceptionFormatter subclass, since those are already
    formatted before they'd ever reach here.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def custom_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except DomainError as exc:
                return to_json_response(build_error_response(exc))

        return custom_handler
