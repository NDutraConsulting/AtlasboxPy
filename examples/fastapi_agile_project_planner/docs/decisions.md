# Architecture decisions

ADRs specific to this example app — not `atlasboxpy_controller`,
`atlasboxpy_repository`, `atlasboxpy_db`, `atlasboxpy_service`,
`atlasboxpy_telemetry`, or `atlasboxpy_api`'s own choices (see each
package's own `docs/decisions.md`), but what this demo does with them.

## Which decision applies to what you're doing

```
Adding a new entity, or deciding where its data should live?
│
├─ Does this entity need its own database instance, a different SQL
│  dialect, or a non-SQL backend entirely?
│    └─→ ADR-1: give it its own infrastructure/database/{tables,db_connections,orm_models}/ (schema, connection config, and query logic, each independently) — a
│         SQLAlchemy{EntityType}Storage class with its own DB_QUANTUM —
│         a config change, not a refactor of anything above it.
│
├─ About to write a SELECT/INSERT/UPDATE directly inside
│  KanbanRepository or KanbanService, or about to return a raw
│  SQLAlchemy row (BoardRow/ColumnRow/CardRow) from one of them?
│    └─→ ADR-1: don't — that belongs in that entity's
│         sqlalchemy_{entity}_storage.py. KanbanRepository orchestrates
│         storage calls and owns the cache; it never opens a SQLAlchemy
│         session or sees a row itself.
│
├─ Tempted to add a generic get/create/update/delete to every entity
│  storage for consistency, or to declare a formal interface class
│  above SQLAlchemy{EntityType}Storage?
│    └─→ ADR-1: no to both — each storage class defines only the
│         operations that entity actually needs (see
│         sqlalchemy_board_storage.py vs. sqlalchemy_card_storage.py —
│         genuinely different shapes), and the contract is that class's
│         own public methods, not a separate Protocol declaring the same
│         thing a second time for an implementation count of one.
│
├─ Does a new repository method need to change two entities that might
│  end up on different DB_QUANTUMs (e.g. create_board's board + its
│  default columns)?
│    └─→ ADR-1's consequence: you no longer get a free atomic
│         transaction across them. Each entity storage commits its own
│         — if you need atomicity, keep those entities on the same
│         quantum, or add compensation/rollback logic explicitly.
│
├─ An entity's access pattern doesn't fit SQL at all (append-only,
│  partition-and-scan; or genuinely unstructured/document-shaped)?
│    └─→ ADR-2: a non-SQL backend gets its own config type (not
│         DBQuantum — see CassandraQuantum) and, if it's a backend
│         that's been deliberately rejected rather than just not built
│         yet (see MongoBoardStorage), a constructor that raises with
│         the reasoning attached instead of silently not existing.
│
├─ Need data from more than one entity (a board's columns and cards, or
│  counts across every board) — tempted to add that assembly to a
│  repository, or to fetch the pieces one `await` after another?
│    └─→ ADR-3: no to both — a repository (`BoardRepository`/
│         `ColumnRepository`/`CardRepository`) only ever fetches/caches
│         its own entity; assembling several entities' data into one
│         response is `KanbanService`'s job, and it fetches them
│         concurrently (`self.gather_named(...)`) since the lookups don't
│         depend on each other.
│
└─ Building a feature that needs more than one *service* — not just
   more than one repository (KanbanService already handles that) — e.g.
   a user's session, their team's cards, and an AI agent's opinion about
   those cards, all in one response?
     └─→ ADR-4: that orchestration belongs in the controller, not in
          any one service calling another service directly. See
          `KanbanController.find_related_tasks_by_card` and
          `atlasboxpy_service`'s own README for the convention this
          follows.
```

---

## ADR-1: Entity-Type Storage (one `SQLAlchemy{EntityType}Storage` class per entity), not one shared session across the whole aggregate

**Context.** `KanbanRepository` originally opened its own SQLAlchemy
sessions directly, querying `BoardRow`/`ColumnRow`/`CardRow` in whatever
combination a method needed — including multi-table operations
(`create_board` inserting a board plus its default columns, `delete_board`
cascading through cards → columns → the board) inside one shared
`async with session:` block, giving those operations a free atomic
transaction. That also meant all three tables were permanently pinned to
one database, and every SQLAlchemy row leaked straight into
`KanbanService` (which reads `.board_id` off a raw `ColumnRow`/`CardRow`)
— nothing stopped a caller from depending on ORM-specific behavior it had
no business knowing about.

**Decision.** Each independently-accessed entity (`Board`, `Column`,
`Card` — see `entities.py` for their plain-dataclass shapes) gets its own
`infrastructure/database/orm_models/{entity_type}_orm_model.py`, with its
connection config in `infrastructure/database/db_connections/` — one file
per *physical database*, not per entity (`kanban_db_quantum.py` today,
since `Board`/`Column`/`Card` still share one SQLite database; see that
file's own docstring for when to split it). A class naming only the
operations that entity actually needs, returning `entities.py`
dataclasses — never a SQLAlchemy row. `KanbanRepository` calls these
classes directly and still owns caching and cache invalidation (that
stays a repository concern, not a per-entity one — see
`atlasboxpy_repository`'s own ADR-1). `DBQuantumRegistry` — now
`atlasboxpy_db`'s, not this app's own code (see
[`packages/atlasboxpy_db/docs/decisions.md`](../../../packages/atlasboxpy_db/docs/decisions.md))
— is the only thing that ever calls `create_async_engine`, caching
engines/session factories by quantum name so entities sharing a quantum
share one connection pool.

**Revised from the first pass: no separate `Protocol` interface.** The
first version of this ADR paired each `SQLAlchemy{EntityType}Storage`
with a hand-written `{EntityType}Storage` `Protocol` in its own file,
reasoning that it kept the interface "backend-neutral" and swappable for
a future `Mongo{EntityType}Storage`. That reasoning doesn't hold up: no
second implementation exists or is planned, so the Protocol didn't buy
swappability — it duplicated each method signature in a second file for
nothing but ceremony. The actual reason `entities.py` dataclasses (not
`BoardRow`) cross this boundary has nothing to do with hypothetical
backend-swapping — a `BoardRow` is session-bound (can raise on detached
attribute access), isn't safely cache-serializable the way
`KanbanRepository.cache.set()` needs, and would leak SQLAlchemy semantics
into `KanbanService` despite its own docstring claiming it does none.
That argument survives entirely without a formal interface: the contract
is `SQLAlchemyBoardStorage`'s own method signatures and return types.
`KanbanRepository` doesn't need to know *how* a storage class does its
job — only that it does — and that's an orchestration boundary
(caller/callee agree on a request/response shape), not a dependency-
injection concern requiring an abstract type in between.

**Alternatives considered**
- Leave one shared session/connection for the whole aggregate (status
  quo) — simplest, keeps free cross-table atomicity, but an entity can
  never be moved to its own database without a rewrite of every method
  that touches it alongside another entity, and nothing stops a raw ORM
  row from leaking past the repository boundary.
- A generic `Storage[T]` interface with uniform `get`/`create`/`update`/
  `delete` for every entity — forces backends with genuinely different
  semantics to fake operations they don't naturally have, and often
  exposes exactly the operations an entity *shouldn't* allow.
- A `Protocol` per entity, kept purely for documentation even with one
  implementation — rejected above: it's a second file restating the
  first file's signatures, not a real abstraction boundary.
- Chosen: one concrete `SQLAlchemy{EntityType}Storage` class per entity,
  each with only the operations that entity's callers actually use. If a
  second backend for one entity is ever genuinely built, that's the
  moment to extract a Protocol from the two real implementations that
  exist by then — not before.

**Consequence worth calling out explicitly: no more free cross-table
atomicity.** `create_board` now calls `self._boards.create(...)` then
`asyncio.gather`s the three `self._columns.create(...)` calls for its
default columns — several separate commits, not one transaction. If the
process dies partway, a board can exist with fewer than its 3 default
columns. This is real, not hidden: it's what "entities can scale
independently" costs. As long as related entities share a quantum
(today, `Board`/`Column`/`Card` all still do — one `KANBAN_DB_QUANTUM`,
one SQLite database), it's a latent risk, not an active one; it becomes
real the moment two entities in the same operation are actually pointed
at different databases — exactly the point at which you'd need to decide
on compensation logic or keeping those specific entities together — not
something to design speculatively before it's needed.

`delete_board` picks its multi-step ordering specifically to cope with
this: it deletes the board row *first*, then cascades to its
cards/columns — not the other way around. A failure between those two
steps leaves the board itself already gone (row deleted, its
`BoardRepository` cache entry invalidated), so `get_board` reports
`not_found` regardless of whether the cascade finished — never a stale
"the board still exists with all its data" response. The cost is
symmetrical to `create_board`'s: a failed cascade leaves orphaned
card/column rows referencing a `board_id` nothing can reach again —
inert, not a correctness bug, but real, and `delete_board` still reports
the failure rather than hiding it. The general rule this follows: when a
multi-entity write can't be atomic, order it so a partial failure fails
*safe* (the user-visible entity point of entry disappears/exists
correctly) rather than *unsafe* (a stale response looks like full
success).

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | A high-write entity (`Card`) can move to its own instance/pool without a low-write one (`Board`) paying for it — more DB compute surface exactly where the throughput need is. `DBQuantumRegistry` caches engines by quantum, so entities sharing one still share a pool. | An operation touching two quanta now makes 2+ round trips/commits instead of one; today (all quanta identical) this is pure overhead with no benefit yet. |
| Portability | `SQLAlchemyBoardStorage`/`SQLAlchemyColumnStorage`/`SQLAlchemyCardStorage` each work identically regardless of which quantum (SQLite, Postgres, MySQL) they're configured for — `KanbanRepository` never changes when one moves. | A genuinely different backend (a document store, an object bucket) still means writing a whole new class by hand — nothing here makes that automatic, Protocol or not. |
| Debuggability | "Which database does this entity use" has one answer, at the top of one small file — one file to read, not two. Storage exceptions are backend-neutral (`StorageTimeout`/`StorageUnavailable`, from `atlasboxpy_db`), so a bug report says what happened, not which SQLAlchemy exception class happened to be raised. | A bug spanning two entities on different quanta now means two connections, two sets of logs, two places to look — instead of one session to inspect. |
| Evolvability | Splitting an entity onto its own database or dialect is a new class plus a `DB_QUANTUM` value — nothing above `KanbanRepository` changes. Each class only grows the operations its own callers actually need, and there's no second file to keep in sync when a method's signature changes. | Multi-entity operations (`create_board`, `delete_board`) have to be re-examined by hand whenever quanta diverge — nothing flags "this used to be atomic and now isn't" for you. |

---

## ADR-2: Non-SQL backends get their own config type; a rejected backend raises with its reasoning attached, not just missing

**Context.** `DBQuantum` is explicitly SQLAlchemy-shaped — a driver enum
of SQL dialects, a URL, an engine. Two situations don't fit that:
(1) an entity whose access pattern is genuinely better served by a
non-relational backend, and (2) a backend the team evaluated and
decided against, where a developer reaching for it later has no way to
tell "not built yet" from "built and rejected on purpose" apart.

**Decision.**
- `infrastructure/database/orm_models/card_activity_log_orm_model.py`
  demonstrates (1): `CardActivityLog` is append-only and queried almost
  exclusively "last N events for this one card" — a Cassandra partition
  (`card_id`) clustered by `logged_at` descending, not a relational
  index. It gets its own `CassandraQuantum` (keyspace, contact points),
  not a `DBQuantum` — matching the Entity-Type Storage spec's own rule
  that a non-SQL backend "receives its own backend configuration type."
  Illustrative like this app's Postgres/MySQL `DB_QUANTUM` examples
  (`cassandra-driver` isn't a real dependency here, and there's no
  cluster to run it against), but its CQL and key modeling are real and
  tested — `cassandra.cluster` is imported lazily inside `__init__`
  (same pattern as `atlasboxpy_repository`'s `RedisCacheBackend`), and
  `tests/test_cassandra_card_activity_log_storage.py` stubs it via
  `sys.modules` to exercise the query-building and entity-mapping logic
  without a live cluster.
- `infrastructure/database/orm_models/mongo_board_orm_model.py` demonstrates (2):
  `MongoBoardStorage.__init__` raises `UnsupportedBackendError`
  immediately, carrying the actual rejection reasoning (Postgres's
  JSONB/pgvector/partitioning cover what MongoDB would have bought,
  with better tooling) as the exception message. Not a
  `NotImplementedError` — that would say "nobody's built this yet,"
  which is a different, false claim.

**Alternatives considered**
- Silently not having a Mongo implementation at all — a developer
  searching for one just doesn't find it, and has no way to tell
  "nobody needed it yet" from "we decided against it" without asking
  someone or digging through old design docs.
- A comment or a doc page recording the Mongo decision, with no code
  artifact — easy to miss, and doesn't stop someone from actually
  trying to wire up `pymongo` before reading it.
- A `NotImplementedError` for the rejected backend — technically
  truthful about "this doesn't exist" but wrong about *why*, and
  invites someone to "finish" it.
- Chosen: a real class matching the naming convention every other
  backend uses, whose only behavior is refusing to construct with the
  reasoning attached — the rejection is as discoverable as an
  implementation would have been.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | `CardActivityLog`'s one-partition-per-card, clustered-descending modeling is exactly what makes "last N events for this card" cheap at real log volume — a relational table would need a secondary index doing more work for the same query. | None of this is exercised against a real cluster here — the performance claim is architectural, not benchmarked in this repo. |
| Portability | `CassandraQuantum`/`MongoQuantum` being distinct from `DBQuantum` means adding a non-SQL backend never has to bend `DBQuantum`'s SQL-dialect assumptions to fit. | A genuinely new backend technology is still a new file, config type, and (if it's a keeper) test suite by hand — nothing here makes onboarding a backend automatic. |
| Debuggability | `UnsupportedBackendError` with the real reasoning turns "why doesn't this exist" from a Slack-history archaeology problem into a one-line stack trace. | `cassandra.cluster`'s lazy import needs a `# type: ignore` since the package isn't installed — a small, contained wart, not a systemic one. |
| Evolvability | If MongoDB is ever reconsidered, there's exactly one place to change the decision (delete/replace `mongo_board_storage.py`) with a clear historical record of why it was rejected in the first place. | The rejection reason is a string constant, not a structured/versioned decision record — if the reasoning itself needs to evolve (a new Postgres feature changes the calculus, say), that's a manual edit here, not something tooling tracks. |

---

## ADR-3: Entity-scoped repositories (`BoardRepository`/`ColumnRepository`/`CardRepository`), not one shared `KanbanRepository` — cross-entity assembly is `KanbanService`'s job

**Context.** ADR-1 moved SQL out of one shared session into three separate
`SQLAlchemy{EntityType}Storage` classes, but the repository layer above
them originally stayed one class: `KanbanRepository` held all three
storages, called them one `await` after another to assemble a board
(`get_board`: board → columns → cards), tallied cross-entity counts
(`list_boards`'s column/card counts), and owned one cache keyed per
assembled board. `KanbanService` just called `KanbanRepository`'s
already-assembled methods — meaning the repository, supposedly the layer
that only knows how to fetch/cache its own data, also had to know
`Board`+`Column`+`Card` exist and how they relate: the same knowledge
`KanbanService` already needed.

**Decision.** `BoardRepository`, `ColumnRepository`, `CardRepository`
(`infrastructure/repositories/`) are each their own
`atlasboxpy_repository.BaseRepository` subclass — own storage, own
cache, own cache keys (`kanban:board:{id}` / `kanban:columns:{board_id}`
/ `kanban:cards:{board_id}`) — and none of them knows the other two
exist. `KanbanService` constructs all three and is the only thing that
calls more than one of them: it fetches a board's board/columns/cards
concurrently via `asyncio.gather` (not sequential awaits — the three
lookups don't depend on each other), tallies `list_boards`'s per-board
counts, and builds every JSON-shaped dict this app's routes return. The
dict-assembly logic that used to live in `KanbanRepository` now lives in
`kanban_service.py`.

**Alternatives considered**
- Leave one `KanbanRepository` owning all three storages, sequential
  `await`s to assemble a board — simplest change, but conflates two
  different jobs in one class: "how do I fetch/cache one entity" (a
  repository's job) and "how do three entities' data combine into one
  board" (an orchestration job, the kind a service does everywhere else
  in this app).
- A single `KanbanRepository` still holding one cache but exposing
  narrower per-entity methods — doesn't remove the coupling: assembling
  a board still means several sequential calls into one object with one
  shared cache config, no clearer than before.
- Per-entity repositories sharing one cache namespace/key scheme owned
  by one of them — rejected: it re-introduces a hidden dependency
  between repositories (one has to know the others' key format), the
  exact thing per-entity ownership is meant to avoid.
- Chosen: three independent repositories, `KanbanService` as the only
  orchestrator, cache moved from "one blob per assembled board" to "one
  entry per entity read" — finer-grained invalidation as a side effect
  (adding a card no longer busts the columns cache, only the cards one).

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | `get_board`'s three lookups run concurrently (`asyncio.gather`) instead of three sequential `await`s — a cache miss on all three now costs roughly one round trip's worth of wall time, not three stacked. | A `get_board` call now always issues (or checks cache for) all three lookups, even when the board doesn't exist — the old code short-circuited after the first `None`. On a genuinely missing board this wastes two lookups; on a real board it's strictly faster than before. |
| Portability | A repository's cache technology (`cache_driver`/`cache_env`) is now a per-entity choice — `Card` (the highest write volume) could move to Redis without `Board`/`Column` following. | Each new entity is a new small repository file to add — no shared base beyond `atlasboxpy_repository.BaseRepository` itself. |
| Debuggability | Invalidation is finer-grained and easier to reason about: "did this write invalidate the right cache" has one answer per entity (`ColumnRepository.create` only ever touches the columns cache), not "does this write correctly invalidate the one shared board blob." | Debugging "why is get_board slow" now means checking three repositories' cache state instead of one — three places to look instead of one, in exchange for each being simpler. |
| Evolvability | A cross-entity rule that changes (e.g., a title uniqueness check spanning cards on the same board) is added to `KanbanService`, which already has to know both entities exist — no repository method to extend. | `KanbanService.__init__` constructs three repositories instead of one, and reads that combine data need an explicit `asyncio.gather` call — nothing routes a new orchestrated entity through automatically. |

---

## ADR-4: Multi-*service* orchestration belongs in the controller, not in one service calling another

**Context.** ADR-3 settled where multi-*repository* orchestration lives
(`KanbanService`, not any one repository). This app now has more than
one bounded context worth its own service: `KanbanService` (boards/
columns/cards), `UserSessionService` (who is this caller and what team
are they on), and `TaskAgentService` (turning card content into tags —
a stub for a real AI-agent call today, see that service's own
docstring). A feature like "find this user's team's cards and tag them"
needs all three. The obvious-looking option is letting `KanbanService`
call `UserSessionService`/`TaskAgentService` directly, the same way it
already calls its own three repositories.

**Decision.** It doesn't. `KanbanService`, `UserSessionService`, and
`TaskAgentService` never call each other — each owns exactly one bounded
concern and has no idea the other two exist. `KanbanController.find_related_tasks_by_card`
is the one place that constructs and calls all three, in the sequence
each step's output requires:

```
UserSessionService.get_user(token)
  -> KanbanService.get_cards_by_team(team_id)
  -> TaskAgentService.tag_cards(cards)
  -> KanbanService.update_card_tags(tag_map)
```

See `atlasboxpy_service`'s own README for the general version of this
rule (a service's job is repositories + third-party/internal-service
calls + its own bounded context's aggregation; orchestrating *other*
services is a controller's job) — this ADR is that convention's worked,
running example.

**Alternatives considered**
- `KanbanService` calls `UserSessionService`/`TaskAgentService` directly
  — the shortest path to a working feature, but it means `KanbanService`
  (a persistence-and-business-rules service for one aggregate) now also
  has to know about session tokens and tagging heuristics — two
  unrelated bounded contexts coupled to a third that has nothing to do
  with either. A change to how sessions work, or a real agent
  integration replacing the tagging stub, would risk touching
  `KanbanService` even though neither concern is board/column/card
  business logic.
- A fourth "orchestration service" that itself calls the other three —
  moves the coupling one level sideways instead of removing it: now
  there's a service whose only job is calling other services, which is
  exactly what a controller already is in this app's layering (`routes
  > controllers > services > infrastructure`, see `main.py`'s own
  docstring) — a redundant layer restating a job the controller already
  has.
- Chosen: the controller is the one place in this app's layering that
  legitimately has no bounded context of its own to protect — its whole
  job is assembling a response for one incoming request, which is
  exactly what cross-service orchestration is.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | `find_related_tasks_by_card`'s four steps are strictly sequential (each needs the previous step's output), so there's no concurrency to gain by moving orchestration to the controller versus a service — this is purely a coupling decision, not a performance one. | — |
| Portability | `UserSessionService`/`TaskAgentService` can each be swapped for a real implementation (real JWT verification, a real agent call) without `KanbanService` — or any other consumer of it — changing at all. | A feature needing several services is now a controller method, not a service method — a caller that only has access to services (a background worker, say) can't reuse `find_related_tasks_by_card`'s orchestration directly; it would need to replicate the sequence itself or the app would need to extract it into a plain function both a controller and a worker could call. |
| Debuggability | Three independently testable services (see `test_user_session_service.py`/`test_task_agent_service.py`) plus one orchestration test (`test_find_related_tasks_by_card_...`) — a bug is traceable to exactly one of those four places, never "somewhere inside a service that calls two other services." | The full picture of "what does finding related tasks actually do" requires reading the controller method, not any single service — there's no one service file that tells the whole story. |
| Evolvability | Adding a fourth service to a future feature (a `NotificationService`, say) is a new class plus a new controller method — no existing service needs to change to accommodate it. | Every new multi-service feature adds another controller method with its own sequential (or, where independent, `gather_named`-based) orchestration — nothing generalizes that pattern across features automatically. |
