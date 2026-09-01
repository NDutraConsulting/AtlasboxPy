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
- [`packages/atlasboxpy_db/`](packages/atlasboxpy_db/) — `DBQuantum` +
  `ShardRouter` for SQLAlchemy: a single physical database is just a
  `ShardRouter` with one shard, not a separate type from a sharded one —
  going to N databases later is a config change, not a migration.
  Also has `VariantRouter`, for picking between a small set of
  semantically *different* databases (a shadow DB seeded with test data
  for post-deploy validation, say) by an exact label — deliberately not
  the same mechanism as sharding (see `atlasboxpy_db`'s own ADR-4).
- [`packages/atlasboxpy_api/`](packages/atlasboxpy_api/) — a
  framework-agnostic ASGI middleware that resolves one HTTP header into
  request-scoped context (`ContextVar`-backed, not a global — no
  leaking between concurrent requests), for things like routing a
  single request to a shadow database via a header without touching a
  process-wide toggle. Pairs with `atlasboxpy_db`'s `VariantRouter` for
  the actual "which database" decision; this package only ever moves a
  header's raw value into request scope.
- [`packages/atlasboxpy_service/`](packages/atlasboxpy_service/) — a
  `BaseService` base class for the layer that orchestrates repositories
  and third-party/internal-service calls on a controller's behalf: the
  same auto-wrapping mechanism as `BaseController`, but logging every
  call's entry *and* outcome (not just failures), plus `gather_named`, a
  reusable named-concurrent-call helper.
- [`packages/atlasboxpy_telemetry/`](packages/atlasboxpy_telemetry/) —
  real (log-based, no external backend required) trace propagation: a
  trace id and parent/child spans threaded through a request via
  `atlasboxpy_api`'s request-scoped context, toggleable by a
  process-wide config default and a per-request header override — enable
  a fully traced call chain for one specific post-prod request, with no
  redeploy.

## Which one do I need?

```
Building something that talks to a database and might need caching?
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                      │
   Need one consistent   Need a pluggable,      Need to configure
   response shape        read-through cache     which physical
   across REST/worker/   in front of your       database (or shard)
   agent callers, with   data access, without   a table lives in,
   error handling that's hand-rolling            decoupled from the
   structural, not       get/set/invalidate      query logic that
   opt-in per route?     plumbing?               uses it?
        │                     │                      │
        ▼                     ▼                      ▼
   atlasboxpy_controller  atlasboxpy_repository  atlasboxpy_db
   (BaseController)       (BaseRepository)       (DBQuantum/ShardRouter)
        │                     │                      │
        └─────────────────────┼──────────────────────┘
                               ▼
             Most real apps use all three together — see
             examples/fastapi_kanban for the full stack.
```

`atlasboxpy_api`, `atlasboxpy_service`, and `atlasboxpy_telemetry` aren't
part of that core three — each is a narrower add-on for a specific need
(request-scoped header context; service-layer logging and concurrent
orchestration; trace propagation) that a real app reaches for once the
core three are already in place, not before. `atlasboxpy_telemetry`
depends on `atlasboxpy_api` directly (the one exception to every package
here being an independent sibling — see `atlasboxpy_telemetry`'s own
ADR-1 for why); every other package has zero required dependency on
another package in this workspace.

Each package's own `docs/decisions.md` has the full ADRs — what was
considered and rejected for its non-obvious choices, with
performance/portability/debuggability/evolvability trade-offs for each:
[`atlasboxpy_controller`](packages/atlasboxpy_controller/docs/decisions.md) ·
[`atlasboxpy_repository`](packages/atlasboxpy_repository/docs/decisions.md) ·
[`atlasboxpy_db`](packages/atlasboxpy_db/docs/decisions.md) ·
[`atlasboxpy_api`](packages/atlasboxpy_api/docs/decisions.md) ·
[`atlasboxpy_service`](packages/atlasboxpy_service/docs/decisions.md) ·
[`atlasboxpy_telemetry`](packages/atlasboxpy_telemetry/docs/decisions.md) ·
[`examples/fastapi_kanban`](examples/fastapi_kanban/docs/decisions.md) (the
Entity-Type Storage pattern, tying the core three packages together —
see below) ·
[`examples/fastapi_agile_project_planner`](examples/fastapi_agile_project_planner/docs/decisions.md)
(everything `fastapi_kanban` has, plus multi-service orchestration,
service-layer logging, and trace propagation — see below).

## Examples

[`examples/`](examples/) has runnable demo apps exercising these packages
together.

- **`examples/fastapi_kanban`** — the focused demo of the core three
  (Starlette + SQLite, real cache invalidation via
  `atlasboxpy_repository`, consistent error handling via
  `atlasboxpy_controller`). Stays as-is; the sections below walk through
  it in detail.
- **`examples/fastapi_agile_project_planner`** — starts as the same app
  (literally a copy, at the point it was branched) plus
  `atlasboxpy_service`/`atlasboxpy_telemetry`/`atlasboxpy_api` wired in,
  and is where this workspace's project-planning and AI-agent-adjacent
  features actually grow over time — see its own
  [`docs/decisions.md`](examples/fastapi_agile_project_planner/docs/decisions.md)
  for `KanbanController.find_related_tasks_by_card`, the worked example
  of a controller orchestrating *three* services
  (`UserSessionService`/`KanbanService`/`TaskAgentService`), each owning
  one bounded concern and never calling each other directly.

### Kanban controller (`atlasboxpy_controller`)

`KanbanController` subclasses `BaseController` and orchestrates
`KanbanService` — nothing more. It constructs the service with no
arguments and never references a persistence-layer type (a DB session, an
engine): that's each entity repository's concern, several layers down
(see the repositories below for how they resolve their own session
factories). Every
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

`create_card` never raises and never talks HTTP directly — it builds one
typed, transport-agnostic response the same way regardless of who's
calling (see "One standardized response, read two ways" below for how
that response still becomes a correct HTTP status when a REST caller is
the one asking). A real bug the service didn't already translate is
still caught by `BaseController`'s wrapper underneath. And because
validation lives in the method next to its model instead of in a route,
reading `create_card` alone tells you everything a call needs —
`board_id`, `column_id`, `title`, `description` — with nothing left
implicit in a separate route file.

### Kanban repositories (`atlasboxpy_repository`) + Entity-Type Storage

`BoardRepository`, `ColumnRepository`, `CardRepository` each subclass
`BaseRepository` and are the only places in this chain that touch
`self.cache` — `KanbanService` and `KanbanController` never see it, and
none of the three repositories knows the other two exist. None talks
SQLAlchemy directly either, or ever sees a raw ORM row: each
independently-accessed entity (`Board`, `Column`, `Card` — plain
dataclasses in `entities.py`) gets its own
`orm_models/{entity_type}_orm_model.py` — a class naming only the
operations that entity needs — with its own connection config in
`db_connections/` (the same two-constants-at-the-top-of-the-file
convention `cache_driver`/`cache_env` already use for caching, applied to
"which database"). No separate interface class sits above it: with one
implementation and no second one planned, that would just be the same
method signatures restated in a second file — the contract is this
class's own public methods and their `Card`/`None` return types:

```python
# examples/fastapi_kanban/app/backend/infrastructure/database/orm_models/card_orm_model.py
class SQLAlchemyCardStorage:
    def __init__(self, sessions: SessionOpener) -> None:
        self._sessions = sessions

    async def create(self, board_id: str, column_id: str, title: str, description: str) -> Card:
        card_id = str(uuid.uuid4())
        async with session_scope(self._sessions) as session:
            session.add(CardRow(id=card_id, board_id=board_id, column_id=column_id,
                                 title=title, description=description))
        return Card(id=card_id, board_id=board_id, column_id=column_id,
                     title=title, description=description)
```

That buys five things:

- **Cache invalidation stays with the entity that owns the data.** Each
  repository only ever invalidates its own cache key
  (`ColumnRepository.create` touches `kanban:columns:{board_id}`,
  nothing else) — there's one place to audit per entity, and adding a
  card no longer busts the columns cache the way one shared "the whole
  board" cache entry used to.
- **An entity's database is a config change, not a refactor.** `Card` (by
  far the highest write volume) can move onto its own instance — more DB
  compute surface, higher throughput, no contention with `Board`'s much
  colder read path — by editing its `db_connections/` config, nothing
  else. `DBQuantumRegistry` (from `atlasboxpy_db`) caches engines/session
  factories by quantum name, so entities that still share one also still
  share a connection pool.
- **Callers see application types, never a SQLAlchemy row.** `SQLAlchemyCardStorage`
  returns `Card` (a plain dataclass) — not because a future backend swap
  demands it, but because a `BoardRow`/`CardRow` is session-bound and
  cache-unsafe: `CardRepository.cache.set()` needs a JSON-serializable
  value, not a live ORM row that can raise once its session closes.
- **The trade-off is explicit, not hidden.** Multi-entity operations
  (`create_board` inserting a board plus its default columns) no longer
  get a free atomic transaction once entities can live on different
  quanta — see [`examples/fastapi_kanban/docs/decisions.md`](examples/fastapi_kanban/docs/decisions.md#adr-1-entity-type-storage-one-sqlalchemyentitytypestorage-class-per-entity-not-one-shared-session-across-the-whole-aggregate)
  for what that costs and when it actually starts to matter, including a
  note on why this design dropped its first-pass `Protocol` interfaces,
  and [ADR-3](examples/fastapi_kanban/docs/decisions.md#adr-3-entity-scoped-repositories-boardrepositorycolumnrepositorycardrepository-not-one-shared-kanbanrepository--cross-entity-assembly-is-kanbanservices-job)
  for why assembling a board out of three entities is `KanbanService`'s
  job, not any one repository's.
- **A non-SQL backend that's been rejected says so, out loud.** Not every
  entity fits SQLAlchemy: `CardActivityLog` (append-only, "last N events
  for this card") gets its own `CassandraQuantum` instead of forcing a
  relational index onto a partition-and-scan access pattern. And when a
  backend was actually considered and turned down — `MongoBoardStorage`
  — its constructor doesn't just not exist; it raises
  `UnsupportedBackendError` with the real reasoning attached (Postgres's
  JSONB/pgvector/partitioning cover what MongoDB would have bought), so a
  developer reaching for Mongo later hits the decision, not silence. See
  [ADR-2](examples/fastapi_kanban/docs/decisions.md#adr-2-non-sql-backends-get-their-own-config-type-a-rejected-backend-raises-with-its-reasoning-attached-not-just-missing)
  for the full rejection reasoning and what was considered instead.

`KanbanService.get_board` — the one expensive assembled read (a board,
its columns, every card nested inside them) — is where those three caches
actually pay off: each repository call below is its own read-through
cache, and the three run concurrently since none depends on the others:

```python
# examples/fastapi_kanban/app/backend/services/kanban_service.py
class KanbanService:
    def __init__(self) -> None:
        self._boards = BoardRepository()
        self._columns = ColumnRepository()
        self._cards = CardRepository()

    async def get_board(self, board_id: str) -> ServiceResult:
        board, columns, cards = await asyncio.gather(
            self._boards.get_by_id(board_id),      # its own cache: kanban:board:{id}
            self._columns.list_for_board(board_id), # its own cache: kanban:columns:{board_id}
            self._cards.list_for_board(board_id),    # its own cache: kanban:cards:{board_id}
        )
        if board is None:
            return ServiceResult.error(f"Board {board_id} not found", code="not_found")
        # ... assemble board + columns + cards into one dict ...
        return ServiceResult.ok(data)
```

Swapping a repository's `cache_driver`/`cache_env` from an in-memory dict
to Redis is a two-constant change, made independently per entity —
`KanbanService` and `KanbanController` never know a cache exists, let
alone which technology backs which entity. Those two constants are also
deployment decisions with nothing to do with a repository's own code:
`BARE_METAL` keeps the cache in-process — nothing shared, nothing
reachable over the network, right for a single instance or an agent
running locally; `REDIS` with `CacheEnv.REMOTE` makes it a cache every
node/replica actually shares (they all point at the same `REDIS_URL`),
and since that's an environment variable, relocating it to a different
cloud account, region, or a network-isolated instance for security
reasons is a config change, not a code change.

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
handshake, no client, no OpenAPI schema to parse — which also simplifies
local development and debugging: an agent (or a human) exploring a change
can call a controller method in a REPL and get the exact same verdict a
deployed REST caller would see, without standing up a server, a network
hop, or distributed request-tracing to explain what happened.

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

**Degraded success** (upstream outage on a read, reported as data instead of an error) — `207` (Multi-Status), not a plain `200`, since the caller got *something*, but not the real thing it asked for:

```json
{
  "status": "success",
  "response_code": 207,
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
async def _call(request: Request, method: _ControllerMethod) -> JSONResponse:
    """Extracts `props` from the request, calls a KanbanController method
    with it, logs the request/response to the traffic log, and converts
    the result to a JSONResponse. Every request that reaches a controller
    passes through here — the one place prop-extraction and logging live,
    instead of every route repeating them."""
    props = await extract_api_request(request)
    result: SuccessResponse[Any] | ErrorResponse = await method(props)
    status = "success" if isinstance(result, SuccessResponse) else result.error.code
    _traffic_log.info(
        "source=%s method=%s status=%s request=%s response=%s",
        json.dumps({"url": request.url.path, "method": request.method, "caller_type": "api_route"}),
        method.__name__,
        status,
        json.dumps(props),
        json.dumps(result.model_dump(mode="json")),
    )
    return to_json_response(result)


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

The agent doesn't need a REST client, an OpenAPI schema, or HTTP-status
guessing to know what happened, and doesn't need a running server to
develop or test against this — it calls the same method a route calls,
with the same one-dict argument, in-process, and gets back a typed,
machine-checkable verdict either way.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE), and each package's own copies.
