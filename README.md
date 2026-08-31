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

`KanbanController` subclasses `BaseController` and orchestrates
`KanbanService` — nothing more. It constructs the service with no
arguments and never references a persistence-layer type (a DB session, an
engine): that's `KanbanRepository`'s concern, several layers down (see the
repository below for how it resolves its own session factory). Every
public async method below is wrapped in a try/except automatically, at
class-definition time — no `try/except` in the method itself, no gateway
object between the caller and the controller — and each takes exactly one
argument, `props` (a plain dict), which it validates for itself via
`validate_props` against the matching model in `models.py`. That model
*is* the method's contract:

```python
# examples/fastapi_kanban/controllers/kanban_controller.py
class KanbanController(BaseController):
    def __init__(self) -> None:
        super().__init__()
        self.service = KanbanService()

    async def create_card(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(CreateCardRequest, props)  # {board_id, column_id, title, description}
        response = self._response_for(
            await self.service.create_card(
                payload.board_id, payload.column_id, payload.title, payload.description
            )
        )
        return self._with_card_title_hint(response)

    async def get_board(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(BoardIdProps, props)  # {board_id}
        # A degraded, clearly-marked response in place of reporting the
        # outage — only for a read; a write just reports the failure.
        response = self._response_for(await self.service.get_board(payload.board_id))
        if isinstance(response, ErrorResponse) and response.error.code == "upstream_error":
            return SuccessResponse(
                data={"id": payload.board_id, "name": "(unavailable — degraded response)", "columns": [], "degraded": True}
            )
        return response

    async def move_card(self, props: dict[str, Any]) -> SuccessResponse[Any] | ErrorResponse:
        payload = validate_props(MoveCardRequest, props)  # {card_id, column_id}
        response = self._response_for(await self.service.move_card(payload.card_id, payload.column_id))
        if isinstance(response, SuccessResponse):
            # A move is a domain event, not just a data read — mark it that
            # way so a caller can tell the two apart from status/response_code
            # alone, no body inspection needed. See "One standardized
            # response, read two ways" below.
            return SuccessResponse(status=ResponseStatus.EVENT_FIRED, response_code=202, data=response.data)
        return response

    def _response_for(self, result: ServiceResult) -> SuccessResponse[Any] | ErrorResponse:
        if result.status == ServiceStatus.SUCCESS:
            return SuccessResponse(data=result.result.data if result.result is not None else None)
        if result.status == ServiceStatus.TIMEOUT:
            return build_error_response(TimedOutError(result.msg))
        error_cls = _ERROR_CODE_TO_DOMAIN.get(result.error_code, UnprocessableError)
        return build_error_response(error_cls(result.msg))
```

Value added: `create_card` never raises and never talks HTTP directly —
it builds one typed, transport-agnostic response the same way regardless
of who's calling (see "One standardized response, read two ways" below
for how that response still becomes a correct HTTP status when a REST
caller is the one asking). A real bug the service didn't already
translate is still caught by `BaseController`'s wrapper underneath. And
because validation lives in the method next to its model instead of in a
route, reading `create_card` alone tells you everything a call needs —
`board_id`, `column_id`, `title`, `description` — with nothing left
implicit in a separate route file.

### Kanban repository (`atlasboxpy_repository`)

`KanbanRepository` subclasses `BaseRepository`. It owns every SQLAlchemy
query — and every persistence decision, full stop: whether to reach into
`self.cache` or hit the database is decided here, and only here, not by
`KanbanService` above it. It's also the *only* class in this chain that
knows `SessionFactory` (a SQLAlchemy type) exists at all — resolving one
with no argument required, via `db.py`'s `get_default_session_factory()`,
the same shared-process-state pattern `db_simulation.py` already uses for
its "is the DB down right now?" flag rather than threading a value through
every constructor between the app entry point and here. `get_board` — the
one expensive assembled read (a board, its columns, every card nested
inside them) — goes through `self.cache`, and every write invalidates that
board's cache entry:

```python
# examples/fastapi_kanban/repositories/kanban_repository.py
cache_driver: CacheDriver = CacheDriver.BARE_METAL      # CacheEnv.REDIS
cache_env: CacheEnv = CacheEnv.LOCAL                    # CacheEnv.REMOTE

class KanbanRepository(BaseRepository):
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        super().__init__(cache_driver=cache_driver, cache_env=cache_env)
        self._session_factory = session_factory or get_default_session_factory()

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

## One standardized response, read two ways

Every `BaseController` method returns the same envelope, and that
envelope carries its own transport-agnostic verdict — not just a
`success`/`error` binary, but a `status` label (`success`, `event-fired`,
`error`, `timeout`, `not-found`, `exception`, `api-error`,
`out-of-memory`, `stack-overflow`) plus a numeric `response_code`
(100-999) alongside it. That's decided once, at the controller, from the
`DomainError` raised or built — not duplicated per transport:

```python
# packages/atlasboxpy_controller/src/atlasboxpy_controller/responses.py
class SuccessResponse(BaseModel, Generic[T]):
    status: ResponseStatus = ResponseStatus.SUCCESS
    response_code: int = 200
    data: T

class ErrorResponse(BaseModel):
    status: ResponseStatus = ResponseStatus.ERROR
    response_code: int = 500
    error: ErrorDetail
```

The point isn't to hide the HTTP status code — `to_json_response()` still
sets a real one on the wire — it's that an **in-process caller never has
to make an HTTP call to find out what `response_code` would have been**.
An agent holding a `KanbanController` instance reads `result.status`/
`result.response_code` straight off the object it already has. No
handshake, no client, no OpenAPI schema to parse — which is also what
makes this pleasant to develop and debug locally: an agent (or a human)
exploring a change can call a controller method in a REPL and get the
exact same verdict a deployed REST caller would see, without standing up
a server, a network hop, or distributed request-tracing to explain what
happened.

**Success** (`create_card`) — `response_code` doubles as the HTTP status
`to_json_response()` sets, so this is `200` on the wire too:

```json
{
  "status": "success",
  "response_code": 200,
  "data": {
    "id": "c3b1f9e2-...",
    "board_id": "b7a2d0aa-...",
    "column_id": "col-1",
    "title": "Write README examples",
    "description": "..."
  }
}
```

**Event-fired** (`move_card`) — a move is a domain event, not just a data
read, so it gets its own status/code (`202`) instead of a plain `success`:

```json
{
  "status": "event-fired",
  "response_code": 202,
  "data": { "id": "c3b1f9e2-...", "column_id": "col-doing" }
}
```

**Validation error** (card title over the demo's 10-character cap):

```json
{
  "status": "error",
  "response_code": 422,
  "error": {
    "code": "validation_failed",
    "message": "Card title must be at most 10 characters (got 27) (hint: card titles are capped at 10 characters in this demo)",
    "details": {}
  }
}
```

**Not found:**

```json
{
  "status": "not-found",
  "response_code": 404,
  "error": {
    "code": "not_found",
    "message": "Board b7a2d0aa-... not found",
    "details": {}
  }
}
```

**Timeout** — distinct from a generic backend failure (`api-error`/502)
on purpose, so a caller can tell "the backend is slow, maybe retry" apart
from "the backend is broken":

```json
{
  "status": "timeout",
  "response_code": 504,
  "error": {
    "code": "timeout",
    "message": "Operation timed out",
    "details": {}
  }
}
```

**Degraded success** (upstream outage on a read, reported as data instead of an error):

```json
{
  "status": "success",
  "response_code": 200,
  "data": {
    "id": "b7a2d0aa-...",
    "name": "(unavailable — degraded response)",
    "columns": [],
    "degraded": true
  }
}
```

### REST API caller

The Starlette route never builds a payload object or imports a Pydantic
model — it merges the request into a `props` dict (via
`atlasboxpy_controller`'s `extract_api_request`) and calls the controller
with nothing else. `_call` (main.py's thin wrapper adding traffic logging
around that same extract-then-format pattern) then uses
`result.response_code` as the actual HTTP status:

```python
# examples/fastapi_kanban/main.py
async def move_card(request: Request) -> JSONResponse:
    return await _call(request, controller.move_card)
```

```bash
curl -s -i -X POST localhost:8000/api/cards/c3b1f9e2.../move \
  -H 'content-type: application/json' -d '{"column_id": "col-doing"}'
# HTTP/1.1 202 Accepted
# {"status":"event-fired","response_code":202,"data":{"id":"c3b1f9e2-...","column_id":"col-doing"}}
```

### AI agent caller

An agent doesn't go through HTTP at all — it holds a `KanbanController`
instance (or a thin tool wrapper around one) and calls the method as a
plain Python coroutine, building the same `props` dict `extract_api_request`
would have built from an HTTP request. It reads `status`/`response_code`
off the result directly, and branches on the same finite vocabulary
regardless of which controller or method it called — no per-endpoint
response schema to learn:

```python
controller = KanbanController()
result = await controller.move_card({"card_id": card_id, "column_id": "col-doing"})

match result.status:
    case ResponseStatus.SUCCESS | ResponseStatus.EVENT_FIRED:
        ...  # use result.data
    case ResponseStatus.TIMEOUT:
        ...  # transient — is_retryable(result.error.code) confirms a retry can help
    case ResponseStatus.NOT_FOUND | ResponseStatus.ERROR:
        ...  # surface result.error.message, maybe ask a clarifying question
    case ResponseStatus.EXCEPTION | ResponseStatus.OUT_OF_MEMORY | ResponseStatus.STACK_OVERFLOW:
        ...  # a real bug, not a business outcome — don't retry blindly, flag it
```

Value added: the agent doesn't need a REST client, an OpenAPI schema, or
HTTP-status guessing to know what happened, and doesn't need a live
server up at all to develop or test against this — it calls the same
method a route calls, with the same one-dict argument, in-process, and
gets back a typed, machine-checkable verdict either way.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE), and each package's own copies.
