from atlasboxpy_api import HeaderContextMiddleware, RequestContext


def _http_scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {"type": "http", "headers": headers}


async def _noop_receive() -> dict:
    return {"type": "http.request"}


async def _noop_send(message: dict) -> None:
    pass


def _resolve(label: str | None) -> str:
    return {"shadow": "shadow-db"}.get(label or "", "prod")


async def test_recognized_header_resolves_to_its_variant():
    ctx: RequestContext[str] = RequestContext("test-mw-recognized", default="prod")
    seen = []

    async def downstream(scope: dict, receive: object, send: object) -> None:
        seen.append(ctx.get())

    middleware = HeaderContextMiddleware(
        downstream, header_name="X-DB-Environment", context=ctx, resolve=_resolve
    )
    await middleware(_http_scope([(b"x-db-environment", b"shadow")]), _noop_receive, _noop_send)

    assert seen == ["shadow-db"]
    assert ctx.get() == "prod"  # reset once the request completes


async def test_missing_header_resolves_to_default():
    ctx: RequestContext[str] = RequestContext("test-mw-missing", default="prod")
    seen = []

    async def downstream(scope: dict, receive: object, send: object) -> None:
        seen.append(ctx.get())

    middleware = HeaderContextMiddleware(
        downstream, header_name="X-DB-Environment", context=ctx, resolve=_resolve
    )
    await middleware(_http_scope([]), _noop_receive, _noop_send)

    assert seen == ["prod"]


async def test_unrecognized_header_value_falls_back_to_default():
    ctx: RequestContext[str] = RequestContext("test-mw-unrecognized", default="prod")
    seen = []

    async def downstream(scope: dict, receive: object, send: object) -> None:
        seen.append(ctx.get())

    middleware = HeaderContextMiddleware(
        downstream, header_name="X-DB-Environment", context=ctx, resolve=_resolve
    )
    await middleware(
        _http_scope([(b"x-db-environment", b"' OR 1=1 --")]), _noop_receive, _noop_send
    )

    assert seen == ["prod"]


async def test_header_name_matching_is_case_insensitive():
    """ASGI always lowercases header names in scope["headers"] regardless
    of the case a client sent — the middleware's own header_name is
    lowercased to match at construction time."""
    ctx: RequestContext[str] = RequestContext("test-mw-case", default="prod")
    seen = []

    async def downstream(scope: dict, receive: object, send: object) -> None:
        seen.append(ctx.get())

    middleware = HeaderContextMiddleware(
        downstream, header_name="X-DB-ENVIRONMENT", context=ctx, resolve=_resolve
    )
    await middleware(_http_scope([(b"x-db-environment", b"shadow")]), _noop_receive, _noop_send)

    assert seen == ["shadow-db"]


async def test_non_http_scope_passes_through_without_touching_context():
    ctx: RequestContext[str] = RequestContext("test-mw-lifespan", default="prod")
    called = []

    async def downstream(scope: dict, receive: object, send: object) -> None:
        called.append(scope["type"])

    middleware = HeaderContextMiddleware(
        downstream, header_name="X-DB-Environment", context=ctx, resolve=_resolve
    )
    await middleware({"type": "lifespan"}, _noop_receive, _noop_send)

    assert called == ["lifespan"]


async def test_context_is_reset_even_if_downstream_raises():
    ctx: RequestContext[str] = RequestContext("test-mw-raises", default="prod")

    async def downstream(scope: dict, receive: object, send: object) -> None:
        raise RuntimeError("boom")

    middleware = HeaderContextMiddleware(
        downstream, header_name="X-DB-Environment", context=ctx, resolve=_resolve
    )
    try:
        await middleware(
            _http_scope([(b"x-db-environment", b"shadow")]), _noop_receive, _noop_send
        )
    except RuntimeError:
        pass

    assert ctx.get() == "prod"


async def test_end_to_end_with_a_real_starlette_app():
    """Proves this genuinely works as ASGI middleware against a real
    framework, not just against hand-built scope dicts."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    ctx: RequestContext[str] = RequestContext("test-mw-e2e", default="prod")

    async def whoami(request: object) -> JSONResponse:
        return JSONResponse({"served_by": ctx.get()})

    app = Starlette(routes=[Route("/whoami", whoami)])
    app.add_middleware(
        HeaderContextMiddleware,
        header_name="X-DB-Environment",
        context=ctx,
        resolve=_resolve,
    )

    with TestClient(app) as client:
        default_resp = client.get("/whoami")
        assert default_resp.json() == {"served_by": "prod"}

        shadow_resp = client.get("/whoami", headers={"X-DB-Environment": "shadow"})
        assert shadow_resp.json() == {"served_by": "shadow-db"}
