"""Application-owned entity types the orm_models/ layer returns — never a
SQLAlchemy row (see tables/), never a dict shaped for the JSON API.
BoardRepository/ColumnRepository/CardRepository each return these
directly; KanbanService converts them into the dict shapes
KanbanController expects while orchestrating all three. Nothing in
database/ ever knows about that shape, and nothing above database/ ever
sees a `BoardRow`/`ColumnRow`/`CardRow` past this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Board:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Column:
    id: str
    board_id: str
    name: str
    position: int


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    board_id: str
    column_id: str
    title: str
    description: str
    # A list, not a tuple, despite every other field here being an
    # immutable scalar: BoardRepository/ColumnRepository/CardRepository
    # cache reads by round-tripping dataclasses.asdict() -> dict ->
    # Card(**d) (see board_repository.py's docstring) — a real Redis
    # backend would json.loads() that dict back, which always produces a
    # list for a JSON array, never a tuple. A tuple field would round-trip
    # as a list anyway (Python doesn't enforce this at runtime), just
    # silently inconsistent with its own type; list avoids that entirely.
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CardActivityLog:
    """One append-only event ("card created", "card moved", ...) — see
    orm_models/card_activity_log_orm_model.py."""

    id: str
    card_id: str
    board_id: str
    action: str
    logged_at: str  # ISO 8601 — also this table's clustering key
