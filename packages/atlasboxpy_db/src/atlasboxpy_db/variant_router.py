"""VariantRouter — exact-match selection between a small set of named,
semantically DIFFERENT deployment targets (e.g. "the real database" vs.
"a shadow database seeded with test data for post-deploy validation").

Deliberately not `ShardRouter`: `ShardRouter` hash-buckets a key across N
INTERCHANGEABLE shards of the *same* dataset, for load distribution — the
same key can land on a different shard if the shard count ever changes,
which is fine for spreading load but would be actively dangerous here (a
config change silently remapping "shadow" traffic onto "prod"). A
`VariantRouter` never buckets or hashes: a label either names a
registered variant exactly, or resolution falls back to `default` —
there is no scenario where an unrecognized or malformed label routes to
anything but the safe default target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class VariantRouter(Generic[T]):
    name: str
    default: T
    variants: dict[str, T] = field(default_factory=dict)

    def resolve(self, label: str | None) -> T:
        """`label` is untrusted input end to end (typically a REST
        header value, resolved by `atlasboxpy_api`'s request-context
        middleware) — `None`, an empty string, or any value not exactly
        matching a registered variant name falls back to `default`.
        Never partial-matches, never raises: a malformed or unrecognized
        label must never be able to reach anything but the safe default
        target."""
        if label is None:
            return self.default
        return self.variants.get(label, self.default)

    def resolved_label(self, label: str | None) -> str:
        """Which label a `resolve()` call actually used — "default" or
        the matched variant name — for logging/observability without
        making every caller re-implement the same matching logic."""
        if label is not None and label in self.variants:
            return label
        return "default"
