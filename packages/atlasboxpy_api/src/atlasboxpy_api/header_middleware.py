"""HeaderContextMiddleware — plain ASGI middleware (no framework
dependency: works unmodified with Starlette, FastAPI, or any ASGI app)
that reads one HTTP header, resolves it through a caller-supplied
function, and makes the result available for the request's duration via
a `RequestContext`.

Deliberately doesn't know what the resolved value even IS — a DB
variant, a feature flag, anything. Composing this with something like
`atlasboxpy_db`'s `VariantRouter` is the caller's job, at the app's own
composition root: this middleware's only responsibility is "read a
header safely, expose the resolved value request-scoped, clean up after
— nothing else."

Security note: `resolve` receives the raw header value completely
untrusted — this middleware applies no validation of its own. What
`resolve` returns is entirely up to the caller; a `VariantRouter`-backed
`resolve` that falls back to a safe default for any unrecognized label
(rather than, say, constructing a resource from the raw string) is what
keeps an arbitrary or malformed header value from reaching anything
sensitive.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from .request_context import RequestContext

T = TypeVar("T")

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class HeaderContextMiddleware(Generic[T]):
    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str,
        context: RequestContext[T],
        resolve: Callable[[str | None], T],
    ) -> None:
        self._app = app
        # ASGI header names in scope["headers"] are always lowercased
        # bytes, regardless of the case a client actually sent.
        self._header_name = header_name.lower().encode("latin-1")
        self._context = context
        self._resolve = resolve

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        header_value = self._extract_header(scope)
        resolved = self._resolve(header_value)
        token = self._context.set(resolved)
        try:
            await self._app(scope, receive, send)
        finally:
            self._context.reset(token)

    def _extract_header(self, scope: Scope) -> str | None:
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        for raw_name, raw_value in headers:
            if raw_name == self._header_name:
                return raw_value.decode("latin-1")
        return None
