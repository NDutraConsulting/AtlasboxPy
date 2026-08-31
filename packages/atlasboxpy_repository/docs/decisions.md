# Architecture decisions

Lightweight ADRs for the choices in this package that a developer
evaluating or extending it would reasonably ask "why not the obvious
alternative?" about. Each one names what was actually considered and
rejected, not a strawman.

## Which decision applies to what you're doing

```
Adding a new repository, or changing an existing one's cache?
│
├─ Does this data ever need to be visible to another process/node?
│    ├─ No  → CacheDriver.BARE_METAL (ADR-1) — in-memory dict, zero setup
│    └─ Yes → CacheDriver.REDIS
│               ├─ Redis runs on the same host as the app → CacheEnv.LOCAL
│               └─ Redis is managed/remote/elsewhere      → CacheEnv.REMOTE
│                    (endpoint from REDIS_URL — relocate by changing
│                     the env var, not the code)
│
├─ About to hand-roll get/set/invalidate calls scattered through this
│  repository's own methods?
│    └─→ ADR-1: don't — subclass BaseRepository and call
│         self.cache.get/set/invalidate; the driver is a two-constant
│         decision at the top of the file.
│
├─ Tempted to configure the driver as a plain string or straight from
│  an env var, per repository?
│    └─→ ADR-2: no — CacheDriver/CacheEnv are typed Enums; only the
│         Redis *endpoint* (REDIS_URL) is deployment-time config.
│
└─ Could a value cached here go stale because something outside this
   app's own invalidate() calls changed the underlying data?
     └─→ ADR-3: yes, by design, for CacheDriver.REDIS — that's what the
          300s TTL safety net is for. BARE_METAL has no such gap, since
          nothing outside this process can write to it.
```

---

## ADR-1: `BaseRepository` subclassing with two config constants, not a decorator or a shared cache client

**Context.** A repository needs read-through caching without hand-rolling
get/set/invalidate plumbing in every method, and different repositories
in the same app might reasonably want different cache technology — a
hot, high-read entity might want Redis; a rarely-read one is fine with an
in-memory dict.

**Decision.** `BaseRepository.__init__(cache_driver=..., cache_env=...)`;
a concrete repository declares its own two constants at the top of its
file and calls `super().__init__(...)`. `self.cache.get/set/invalidate`
is the only surface the subclass ever touches.

**Alternatives considered**
- A `@cached(ttl=...)` decorator on individual methods — implicit;
  invalidation (a write clearing a read's cache entry) has no natural
  place to live, since the decorator only ever sees one method at a time.
- A single shared, app-wide cache client every repository is handed —
  forces every repository in the app to agree on one technology; a hot
  entity and a cold one can't make independent choices.
- Chosen: base-class subclassing — the decision lives with whoever owns
  that repository's data access, as a two-line, type-checked declaration.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | `BARE_METAL`'s in-memory dict has zero network/serialization overhead; `REDIS` only pays a network round trip for repositories that actually opt into it. | `RedisCacheBackend` JSON-encodes every value on write and decodes on read — a real, if small, cost compared to a backend that stored native objects. |
| Portability | `redis` is only imported inside `RedisCacheBackend.__init__`, not at module load — a repository using `BARE_METAL` never needs the `redis` package installed at all. | — |
| Debuggability | `self.cache.get(key)` reads identically in source regardless of which driver backs it — stepping through a method never differs based on deployment config. | A `BARE_METAL` cache is invisible from outside the process (nothing to inspect with `redis-cli`); debugging "why is this stale" looks different locally than in an environment running `REDIS`. |
| Evolvability | Moving a repository from `BARE_METAL` to `REDIS` (or back) is a two-constant edit, no change to any method body. | `CacheBackend`'s interface (get/set/invalidate by string key) is deliberately minimal — a need that doesn't fit that shape (pattern-based invalidation, pub/sub) requires extending the backend interface itself, not just picking a config value. |

---

## ADR-2: `CacheDriver`/`CacheEnv` as real Enums, not strings or env-var-driven selection

**Context.** Cache driver/environment selection could be a plain string
(`cache_driver = "redis"`), read directly from an environment variable at
runtime, or a typed value checked before the code ever runs.

**Decision.** `CacheDriver`/`CacheEnv` are `str, Enum` subclasses; a
repository assigns `cache_driver: CacheDriver = CacheDriver.BARE_METAL` —
a real, type-checked value, not a bare string. Only the Redis *endpoint*
(`CacheEnv.REMOTE`'s `REDIS_URL`) is read from the environment — the
code-level decision (which driver) is not.

**Alternatives considered**
- Bare strings (`cache_driver = "redis"`) — a typo (`"raedis"`) is a
  runtime error the first time that branch executes, not something a type
  checker catches before the code ever runs.
- Reading the driver itself from an environment variable per repository —
  conflates a code-level decision (does this entity's data belong in a
  shared cache at all) with a deployment-level one (where does that Redis
  instance live), when the two are actually independent.
- Chosen: typed Enum for the code-level decision; an environment variable
  only for the deployment-level detail `CacheEnv.REMOTE` already
  delegates to.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | No runtime difference from a plain string — this decision is about correctness and tooling, not speed. | — |
| Portability | Both are `str` subclasses, so anywhere a plain string is expected (a log line, an f-string) they behave like one — no adapter code needed. | — |
| Debuggability | `mypy --strict` (this package's own config) catches an invalid driver value before the code ever runs; a bare string wouldn't be caught until the wrong branch executed. | — |
| Evolvability | Adding a third driver (say, `MEMCACHED`) is one new Enum member plus one new `CacheBackend` subclass — every existing repository's `self.cache` call sites are unaffected. | — |

---

## ADR-3: A 300-second TTL on Redis-cached values, not unbounded storage relying solely on explicit invalidation

**Context.** `BaseRepository`'s read-through cache invalidates on writes
that go through the same repository's own methods — but a value in a
shared Redis cache can also go stale from something outside this app's
own `invalidate()` calls: a direct database write, or a different service
instance writing to the same underlying data without going through this
repository.

**Decision.** `RedisCacheBackend` sets every cached value with `ex=300`
(a 5-minute TTL) on `.set()`. `BareMetalCacheBackend` has no such TTL — it
can't go stale from outside the process, since nothing outside the
process can reach it.

**Alternatives considered**
- No TTL, rely purely on explicit `invalidate()` calls — correct only if
  every writer of this data always goes through this same repository; a
  direct DB write or a second app instance sharing the same Redis would
  leave a stale entry cached forever.
- A much shorter TTL (defeats the point of caching an expensive read) or
  a much longer one (defeats the safety net) — 300s is this package's own
  chosen middle ground, not derived from any specific entity's access
  pattern.
- Chosen: 300s TTL as a bounded worst case, on top of (not instead of)
  explicit invalidation on every write this app itself makes.

**Consequences**

| | Pros | Cons |
|---|---|---|
| Performance | Bounds the "serving stale data" worst case without giving up the read-through cache's benefit for the common case. | A legitimately still-valid cached value gets evicted and re-fetched every 300s even if nothing ever changed it — wasted work when the data really is static. |
| Portability | `BARE_METAL` needs no TTL at all — a repository that never uses Redis never pays this cost or complexity. | — |
| Debuggability | "How stale can this possibly be" has one fixed, documented answer (≤300s), instead of depending on whether every writer remembered to invalidate. | A bug that only manifests after 5 minutes of a value sitting cached is slower to reproduce locally than one that manifests immediately. |
| Evolvability | Invisible to a repository subclass — nothing to update there if the TTL policy changes. | The TTL is currently one package-wide constant (`_TTL_SECONDS = 300`) — a repository can't currently ask for a longer or shorter TTL for its own access pattern without a code change to `atlasboxpy_repository` itself. |
