"""MongoBoardStorage — a deliberate rejection, not an unfinished
implementation. It exists so a developer searching for "how would I back
`boards` with MongoDB" finds an authoritative answer here instead of
reaching for `pymongo`, discovering it's not a dependency, and assuming
it was just never gotten around to.

Raises UnsupportedBackendError immediately on construction, with the
reasoning attached — matching the Entity-Type Storage spec's own rule
that a non-SQL backend "receives its own backend configuration type and
implementation" (see db_connections/mongo_quantum.py, whose MongoQuantum
raises the same way) rather than being shoehorned under DBQuantum, but
going one step further here: this backend was evaluated and rejected on
purpose, not merely never built.
"""

from __future__ import annotations

from atlasboxpy_db import UnsupportedBackendError

from ..db_connections.mongo_quantum import MONGODB_REJECTED_REASON, MongoQuantum


class MongoBoardStorage:
    def __init__(self, quantum: MongoQuantum) -> None:
        raise UnsupportedBackendError(MONGODB_REJECTED_REASON)
