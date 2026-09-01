# atlasboxpy-service

`BaseService`: the same auto-wrapping mechanism as `atlasboxpy_controller`'s
`BaseController` (every public async method on a subclass gets wrapped
at class-definition time), aimed at the service layer instead of the
controller layer — every wrapped method is logged both when it's called
and when it completes, success or failure, through `self.logger`. Also
gives services `gather_named`, a reusable way to run several named calls
concurrently with per-call logging, instead of hand-writing
`asyncio.gather(...)` at every call site.

## Install

> **This is a prototype/example project — it is not published to PyPI and there's no plan to.** The `pip install` commands below are illustrative only; install from a local clone with `pip install -e .` to actually use it.

```bash
pip install atlasboxpy-service
```

## Usage

```python
from atlasboxpy_service import BaseService

class KanbanService(BaseService):
    def __init__(self) -> None:
        super().__init__()
        self._boards = BoardRepository()
        self._columns = ColumnRepository()
        self._cards = CardRepository()

    async def list_boards(self) -> ServiceResult:
        # Before: three hand-written asyncio.gather(...) calls, no
        # per-call visibility into which one was slow or which failed.
        results = await self.gather_named(
            boards=self._boards.list_all(),
            column_counts=self._columns.count_grouped_by_board(),
            card_counts=self._cards.count_grouped_by_board(),
        )
        # results == {"boards": [...], "column_counts": {...}, "card_counts": {...}}
        ...
```

Every call to `list_boards` above now logs, through `self.logger`:
`service_call method=list_boards ...` (entry), one `service_call_concurrent
name=... status=start/ok` line per named call inside `gather_named`, and
a final `service_call method=list_boards status=ok ...` line — the same
kind of visibility `BaseController` already gives a route, one layer
down, without a single log statement written by hand.

## What counts as a service's job (and what doesn't)

This is the convention `BaseService` is built around — useful both for a
human deciding where new logic belongs, and as a reference a coding
agent can use to draw the same boundary consistently:

- **A service's job:** call its own repositories, call third-party APIs
  and other internal services it genuinely depends on, and define the
  *aggregated* concerns of its own bounded context — the loading,
  extraction, and transformation needed to turn raw data into a response
  shape useful to whatever calls it. A service owns one bounded context
  (e.g. `KanbanService` owns boards/columns/cards together, because
  they're one aggregate, not three).
- **Not a service's job: orchestrating *other services*.** A service
  calling another service directly means two bounded contexts are now
  coupled to each other's internals, and nothing owns the combined
  result. That coordination belongs to the **controller** — it's the
  layer that already exists specifically to orchestrate on behalf of one
  incoming request, has no bounded context of its own to protect, and
  is where a multi-service response actually gets assembled.

Worked example — a controller method that needs a user's team, that
team's cards, and an AI agent's tags for those cards, then writes the
tags back:

```python
class KanbanController(BaseController):
    async def find_related_tasks_by_card(self, props: dict) -> SuccessResponse | ErrorResponse:
        payload = validate_props(FindRelatedTasksRequest, props)

        user = await self.user_sessions.get_user(payload.token)          # UserSessionService
        cards = await self.kanban.get_cards_by_team(user.team_id)        # KanbanService
        tag_map = await self.task_agent.tag_cards(cards)                 # TaskAgentService
        updated = await self.kanban.update_card_tags(tag_map)            # KanbanService

        return self._response_for(updated)
```

`KanbanService` never imports or calls `TaskAgentService` or
`UserSessionService` — it has no idea they exist. The controller is the
only thing that knows this particular response needs all three. See
`examples/fastapi_agile_project_planner` for the full, running version
of this example.

## What this package does and doesn't do

- **Does:** wrap every public async method on a `BaseService` subclass
  to log its call and outcome (success or failure, with duration) — the
  service-layer counterpart to what `BaseController` already does for
  controllers, minus the exception-to-response translation (a
  controller's job, not a service's).
- **Does:** `gather_named(**calls)` — run several awaitables
  concurrently with per-call start/success/failure logging, propagating
  the first exception raised.
- **Doesn't:** know `ServiceResult`, `DomainError`, or any specific
  return/exception shape exists. `BaseService` logs whatever a method
  returns or raises generically — it has zero dependency on
  `atlasboxpy_controller` or any particular response envelope.
- **Doesn't:** decide what belongs in a service versus a controller for
  you — see "What counts as a service's job" above for the convention,
  but nothing here enforces it at runtime.

## Documentation

- [`docs/decisions.md`](docs/decisions.md) — ADRs for the non-obvious
  choices (logging both outcomes instead of just failures, re-raising
  rather than translating unexpected exceptions, `gather_named`'s
  propagate-on-first-failure semantics), each with alternatives
  considered and performance/portability/debuggability/evolvability
  trade-offs.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
