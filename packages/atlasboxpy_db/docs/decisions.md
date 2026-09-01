# Architecture decisions

Lightweight ADRs for the choices in this package that a developer
evaluating or extending it would reasonably ask "why not the obvious
alternative?" about. Each one names what was actually considered and
rejected, not a strawman.

## Which decision applies to what you're doing

```
Configuring a database connection, or thinking about sharding?
│
├─ Declaring a new physical database for the first time?
│    └─→ ADR-1: wrap it in a ShardRouter with one shard, not a bare
│         DBQuantum — going to N shards later is then a config change,
│         not a migration to a different type.
│
├─ About to shard by Python's built-in hash(key) or a modulo on an
│  integer id?
│    └─→ ADR-2: don't — hash() is randomized per process
│         (PYTHONHASHSEED); the same key would route to a different
│         shard after every restart. Use ShardRouter's stable hash.
│
├─ Tempted to construct one DBQuantumRegistry at import time and share
│  it across your whole app/test suite?
│    └─→ ADR-3: don't — construct one per app/process instance instead;
│         that's what gives a test suite isolated engines for free.
│
└─ Need to pick between a small set of semantically DIFFERENT databases
   (the real one vs. a shadow database seeded with test data, say) —
   tempted to reach for ShardRouter with a fixed key per variant?
     └─→ ADR-4: don't — use VariantRouter instead. ShardRouter hash-
          buckets a key across INTERCHANGEABLE shards of the same
          dataset; a config change (adding a shard) can silently remap
          which shard a key lands on. VariantRouter never buckets: a
          label matches a registered variant exactly, or falls back to
          `default` — there's no scenario where it lands on the wrong
          database.
```

---

## ADR-1: `ShardRouter` is the base case; a single database is a one-shard router, not a separate type

**Context.** A connection-config package for SQLAlchemy could model
"one database" and "N sharded databases" as two different types — a
plain `DBQuantum` for the common case, and a separate `ShardedDBQuantum`
(or similar) bolted on for when sharding is actually needed. That's the
more obvious design, and it's what an earlier draft of the app this
package was extracted from actually did.

**Decision.** There's only one router type, `ShardRouter[T]`, generic
over whatever connection-config type it routes to (`DBQuantum` here; it
works for a Cassandra or Mongo config just as well). A single-database
deployment is `ShardRouter(name=..., shards=[one_quantum])` — every key
routes to that one shard, because `shard_for(key)` always returns
`shards[hash(key) % len(shards)]`, and `len(shards) == 1` makes the
modulo trivial. Going from one database to many is adding shards to the
same router, not swapping types.

**Alternatives considered**
- A separate `ShardedDBQuantum` (or similar) alongside a plain
  `DBQuantum`, with `DBQuantumRegistry` accepting either — two types to
  keep in sync, two code paths in the registry, and a real migration
  (change the type, change every call site) the day a single-database
  deployment actually needs a second shard.
- A router that only accepts 2+ shards, forcing callers to pick a
  different construction path for the single-database case — rejected
  for the same reason: it makes "no sharding" a distinct case instead of
  the trivial instance of the general one.
- Chosen: one type, one shard being the degenerate (not special) case.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | A one-shard router's `shard_for(key)` still computes a hash and a modulo-by-1 on every call — negligible, but not literally free the way returning a constant would be. | — |
| Portability | The same `DBQuantumRegistry.sessions(router, shard_key=...)` call shape works whether `router` has 1 shard or 100 — a caller never needs to know which, or branch on it. | `ShardRouter` itself has no idea what a "database" is — it's plumbing, not a connection; every concrete use (like `DBQuantum`) still has to be written by hand. |
| Debuggability | "How many shards does this quantum have" is one property (`shard_count`) — no separate "is this even sharded" question to answer first. | A caller who doesn't pass `shard_key` and expects "the same key I'd use later" to matter won't notice it doesn't (yet) — the router silently ignores the key's *value* until there's more than one shard. |
| Evolvability | Real sharding, when it's actually needed, is adding entries to `shards=[...]` and starting to pass real shard keys — no type to migrate off of, no call site to rewrite from "quantum-shaped" to "router-shaped" because it already was one. | — |

---

## ADR-2: A stable hash (SHA-256), not Python's built-in `hash()`

**Context.** Routing a key to a shard needs the same key to always land
on the same shard — across every server, and after a restart. Python's
built-in `hash()` for strings is deliberately randomized per process
(`PYTHONHASHSEED`, a security hardening measure against hash-flooding
attacks) — exactly the property that makes it *unsafe* for this.

**Decision.** `ShardRouter._bucket(key)` hashes with `hashlib.sha256`
and takes a modulo over the first 8 bytes of the digest — deterministic
across processes, machines, and restarts.

**Alternatives considered**
- Python's built-in `hash()` — the obvious first reach, and silently
  wrong: two processes (or the same process before and after a restart)
  would route the same key to different shards, which for a database
  connection means "your data moved to a different shard for no reason
  you did."
- `zlib.crc32` or another non-cryptographic checksum — faster than
  SHA-256, and would have worked; SHA-256 was chosen for being already a
  stdlib import with no subtlety about output distribution to reason
  about, not for any security property (this isn't a security use case).
- Chosen: SHA-256, truncated to 8 bytes before the modulo.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | SHA-256 over a short key is microseconds — irrelevant next to an actual network round trip to the database it's routing to. | A non-cryptographic hash (crc32, murmur) would be measurably faster in a hot loop calling `shard_for` millions of times — not a real workload here, but a real cost if `ShardRouter` were ever reused somewhere latency-sensitive at that scale. |
| Portability | `hashlib` is stdlib — no extra dependency, works identically on every platform Python runs on. | — |
| Debuggability | A given key's shard is computable by hand (`sha256(key).digest()[:8]` mod shard count) from outside the running process — useful when debugging "why did this end up on shard 2." | — |
| Evolvability | Adding or removing shards changes `len(shards)`, which changes the modulo for *every* key, not just new ones — this router doesn't attempt consistent hashing (minimal remapping on resize). Fine for a small, rarely-resized shard count; a real re-sharding at scale needs a different algorithm, deliberately out of scope here. | Same point, as a con: growing a shard count is a real data-migration event (most keys change shards), not a no-op — nothing in this package pretends otherwise. |

---

## ADR-3: A registry is constructed fresh per app/process instance, not a module-level singleton

**Context.** `DBQuantumRegistry` caches engines and session factories by
name. The natural-looking shortcut is a module-level singleton (`registry
= DBQuantumRegistry()` at import time) — one registry the whole process
shares, no explicit construction/wiring needed anywhere.

**Decision.** `DBQuantumRegistry` is a plain class with no module-level
instance; the caller (an app's composition root) constructs one per app
instance and threads it through explicitly (or via its own
process-shared-state convention, as `atlasboxpy_db`'s example app does).

**Alternatives considered**
- A module-level singleton — the shortest path to "it just works," but
  it means a test suite constructing multiple app instances (one per
  test, for isolation) shares ONE registry across all of them: engines
  from test 1's in-memory database would still be cached under the same
  quantum name when test 2 runs, unless every test remembered to reset
  it — a footgun a fresh-per-instance registry makes structurally
  impossible instead of a discipline to maintain.
- Chosen: explicit construction, explicit wiring.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | No difference — construction cost is negligible either way. | — |
| Portability | A registry has no hidden dependency on "the one process-wide instance" existing — it's just an object, testable and constructible anywhere, including multiple at once in the same process if that's ever useful. | — |
| Debuggability | Test isolation is a structural consequence of "who constructs the registry and when," not a convention every test has to remember to uphold — a whole class of "test 2 saw test 1's cached connection" bugs simply can't happen. | A caller does have to actually construct and pass the registry somewhere — one explicit step a singleton would have hidden. |
| Evolvability | An app can run multiple independent registries side by side (say, one per tenant) without this package needing to know that's happening. | — |

---

## ADR-4: `VariantRouter` is a separate type from `ShardRouter`, not a reused one

**Context.** A real use case for this package: routing a request to one
of a small set of *semantically different* databases based on an
untrusted label — e.g. a REST header selecting between the real database
and a shadow database seeded with test data, for validating a vertical
slice of logic against real code paths right after a deploy without
touching production data. `ShardRouter` already routes a string key to
one of N targets — the obvious first reach is to reuse it, giving the
label as the shard key.

**Decision.** `VariantRouter[T]` is a distinct type: a plain exact-match
lookup (`variants: dict[str, T]`) with a required `default`, not a hash
bucket. `resolve(label)` returns `variants[label]` if `label` matches a
registered name exactly, otherwise `default` — always, including for
`None`, an empty string, or any string that isn't a registered variant
name. There is no hashing, no modulo, and no scenario where an
unrecognized label lands on anything but `default`.

**Alternatives considered**
- Reusing `ShardRouter`, treating each variant name as a distinct
  "shard" — rejected: `ShardRouter.shard_for(key)` hash-buckets `key`
  across `len(shards)` targets, and which shard a given key lands on
  depends on the *shard count*. Add a third variant later (a "staging"
  target, say) and every existing key's bucket index can shift — for a
  shard-routed dataset that's an accepted, documented trade-off (ADR-1/2
  in this file); for semantically different databases, it means a
  routing-table change could silently start sending "shadow"-labeled
  traffic at "prod" (or the reverse) with no code change at the call
  site to blame. A hash-based router is the wrong abstraction for
  "exactly this label, or the safe default" — it optimizes for spreading
  load evenly, a property nobody wants here.
- A `VariantRouter` that raises on an unrecognized label instead of
  falling back to `default` — rejected for this use case: the label
  is untrusted end-to-end (typically a REST header — see
  `atlasboxpy_api`), and a malformed or unexpected value must never be
  able to turn into an error path that's easier to probe than the
  default one; falling back silently to the known-safe default is the
  conservative choice. A caller that wants to *know* whether the label
  actually matched (for logging) has `resolved_label()` for that,
  separately from `resolve()`'s value.
- Chosen: a new type, exact-match only, safe-by-construction fallback.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | A dict lookup, not a hash-and-modulo over a digest — marginally cheaper than `ShardRouter`, though neither cost is meaningful next to an actual DB round trip. | — |
| Portability | Generic over `T`, same as `ShardRouter` — works for a `DBQuantum`, a `ShardRouter[DBQuantum]` (picking between a prod router and a shadow router, each of which can still have its own shard count), or anything else with a small, named set of alternatives. | Two very similarly-named types (`ShardRouter`/`VariantRouter`) in one package is a real cost — a developer has to know which one applies (see the map at the top of this file) rather than there being one router type for everything. |
| Debuggability | `resolved_label()` tells a caller exactly which variant served a given request — "default" or the matched name — for logging, without re-implementing the match. | — |
| Evolvability | Adding a new variant is one new dict entry — existing labels' resolution never changes as a side effect, unlike `ShardRouter`'s shard-count-dependent bucketing. | `VariantRouter` intentionally has no `all_variants()`/enumeration helper the way `ShardRouter.all_shards()` does — the point is that a caller never routes to anything it didn't explicitly ask for by exact label, not that every registered variant is discoverable at runtime. |
