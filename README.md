# Controller Gateway

A small workspace of independent, flat-named Python packages — each its
own `pyproject.toml`, installable on its own, no shared namespace between
them (see [`packages/atlasboxpy_controller/CHANGELOG.md`](packages/atlasboxpy_controller/CHANGELOG.md)
for why: PyTorch/NumPy/ROS/Flask all settled on this shape for a family of
related packages, not PEP 420 namespace packages).

## Packages

- [`packages/atlasboxpy_controller/`](packages/atlasboxpy_controller/) —
  a `BaseController` base class that wraps every public async method
  automatically, so a call from an API route, a worker, or an agent
  always comes back as a formatted `SuccessResponse`/`ErrorResponse` —
  no gateway object, no per-method decorator, no `try/except` in your
  routes.
- [`packages/atlasboxpy_repository/`](packages/atlasboxpy_repository/) —
  a `BaseRepository` base class with a pluggable, read-through cache —
  swap between an in-memory dict and Redis via two config constants.

## Examples

[`examples/`](examples/) has runnable demo apps exercising both packages
together — see `examples/fastapi_kanban` for the fullest one (Starlette +
SQLite, real cache invalidation via `atlasboxpy_repository`, consistent
error handling via `atlasboxpy_controller`).

### Kanban controller (`atlasboxpy_controller`)

`KanbanController` subclasses `BaseController`. Every public async method
below is wrapped in a try/except automatically, at class-definition time —
no `try/except` in the method itself, no gateway object between the
caller and the controller:

```python
# examples/fastapi_kanban/controllers/kanban_controller.py
class KanbanController(BaseController):
    def __init__(self, service: KanbanService) -> None:
        super().__init__()
        self.service = service

    async def create_card(self, board_id: str, payload: Any) -> SuccessResponse[Any] | ErrorResponse:
        response = self._response_for(
            await self.service.create_card(
                board_id, payload.column_id, payload.title, payload.description
            )
        )
        return self._with_card_title_hint(response)

    async def get_board(self, board_id: str) -> SuccessResponse[Any] | ErrorResponse:
        # A degraded, clearly-marked response in place of reporting the
        # outage — only for a read; a write just reports the failure.
        response = self._response_for(await self.service.get_board(board_id))
        if isinstance(response, ErrorResponse) and response.error.code == "upstream_error":
            return SuccessResponse(
                data={"id": board_id, "name": "(unavailable — degraded response)", "columns": [], "degraded": True}
            )
        return response

    def _response_for(self, result: ServiceResult) -> SuccessResponse[Any] | ErrorResponse:
        if result.status == ServiceStatus.SUCCESS:
            return SuccessResponse(data=result.result.data if result.result is not None else None)
        if result.status == ServiceStatus.TIMEOUT:
            return build_error_response(UpstreamServiceError(result.msg))
        error_cls = _ERROR_CODE_TO_DOMAIN.get(result.error_code, UnprocessableError)
        return build_error_response(error_cls(result.msg))
```

Value added: `create_card` never raises and never builds an HTTP status —
it builds a typed response the same way regardless of who's calling. A
real bug the service didn't already translate is still caught by
`BaseController`'s wrapper underneath.

### Kanban repository (`atlasboxpy_repository`)

`KanbanRepository` subclasses `BaseRepository`. It owns every SQLAlchemy
query; the service never touches a session. `get_board` — the one
expensive assembled read (a board, its columns, every card nested inside
them) — goes through `self.cache`, and every write invalidates that
board's cache entry:

```python
# examples/fastapi_kanban/repositories/kanban_repository.py
cache_driver: CacheDriver = CacheDriver.BARE_METAL      # CacheEnv.REDIS
cache_env: CacheEnv = CacheEnv.LOCAL                    # CacheEnv.REMOTE

class KanbanRepository(BaseRepository):
    def __init__(self, session_factory: SessionFactory) -> None:
        super().__init__(cache_driver=cache_driver, cache_env=cache_env)
        self._session_factory = session_factory

    async def get_board(self, board_id: str) -> dict[str, Any] | None:
        cache_key = self._board_cache_key(board_id)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached
        # ... assemble board + columns + cards from SQLAlchemy ...
        await self.cache.set(cache_key, data)
        return data

    async def add_card(self, board_id: str, column_id: str, title: str, description: str) -> dict[str, Any]:
        # ... insert CardRow ...
        await self.cache.invalidate(self._board_cache_key(board_id))
        return _card_dict(card)
```

Value added: swapping `cache_driver`/`cache_env` from an in-memory dict to
Redis is a two-constant change — `KanbanService` and `KanbanController`
never know a cache exists, let alone which technology backs it.

## Same call, two callers

Every controller method returns the same `SuccessResponse`/`ErrorResponse`
envelope no matter who calls it — a REST route over HTTP, or an AI agent
calling the controller directly as a tool. There's no gateway object and
no per-caller adapter to keep in sync.

**Success** (`create_card`):

```json
{
  "status": "success",
  "data": {
    "id": "c3b1f9e2-...",
    "board_id": "b7a2d0aa-...",
    "column_id": "col-1",
    "title": "Write README examples",
    "description": "Add kanban usage to the top-level README"
  }
}
```

**Validation error** (card title over the demo's 10-character cap):

```json
{
  "status": "error",
  "error": {
    "code": "validation_failed",
    "message": "Card title must be at most 10 characters (got 27) (hint: card titles are capped at 10 characters in this demo)",
    "details": {}
  }
}
```

**Degraded success** (upstream/DB outage on a read, reported as data instead of a 5xx):

```json
{
  "status": "success",
  "data": {
    "id": "b7a2d0aa-...",
    "name": "(unavailable — degraded response)",
    "columns": [],
    "degraded": true
  }
}
```

### REST API caller

The Starlette route validates the request body, then calls the controller
method directly — no gateway, no handler layer:

```python
# examples/fastapi_kanban/main.py
async def create_card(request: Request) -> JSONResponse:
    payload = await validate_body(request, CreateCardRequest)
    return await _call(request, controller.create_card, request.path_params["board_id"], payload)
```

`to_json_response()` maps the envelope to an HTTP response — 200 for
`SuccessResponse`, the `DomainError`'s mapped status for `ErrorResponse`
(422 for `validation_failed` above):

```bash
curl -s -X POST localhost:8000/api/boards/b7a2d0aa.../cards \
  -H 'content-type: application/json' \
  -d '{"column_id": "col-1", "title": "a much too long title", "description": "..."}'
# HTTP/1.1 422 Unprocessable Entity
# {"status":"error","error":{"code":"validation_failed", ...}}
```

### AI agent caller

An agent doesn't go through HTTP at all — it holds a `KanbanController`
instance (or a thin tool wrapper around one) and calls the method as a
plain Python coroutine, getting back the exact same envelope shape. Its
tool-result parser only needs to understand one shape, regardless of
which controller or method it called:

```python
controller = KanbanController(service)

async def create_card_tool(board_id: str, column_id: str, title: str, description: str) -> dict:
    payload = CreateCardRequest(column_id=column_id, title=title, description=description)
    response = await controller.create_card(board_id, payload)
    return response.model_dump(mode="json")  # same {"status": ..., ...} shape as the REST response above

result = await create_card_tool("b7a2d0aa-...", "col-1", "Write README examples", "...")
if result["status"] == "error":
    # agent can retry, ask a clarifying question, or surface result["error"]["message"] —
    # is_retryable(result["error"]["code"]) says whether a retry could ever succeed
    ...
```

Value added: the agent doesn't need a REST client, an OpenAPI schema, or
HTTP-status guessing to know what happened — it calls the same method a
route calls and gets back a typed, machine-checkable result either way.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE), and each package's own copies.
