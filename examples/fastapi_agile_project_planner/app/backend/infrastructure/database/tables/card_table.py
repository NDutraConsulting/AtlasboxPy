"""The `cards` table — schema only, no query logic. See
infrastructure/database/orm_models/card_orm_model.py for the class that
actually queries this.

Deliberately denormalizes `board_id` alongside `column_id` (rather than
requiring a join through `columns`) so a card query never needs to know
the `columns`/`boards` schema at all — it only ever queries its own
`cards` table, filtered/grouped by the ids it's given.

`tags` is a JSON-encoded string, not a real relational column — cards
need at most a handful of tags each and are never queried *by* tag, so a
join table would buy nothing a single column doesn't already give.
`orm_models/card_orm_model.py` is the only place that encodes/decodes
it; nothing above the storage layer ever sees the raw JSON string (see
`entities.py`'s `Card.tags: list[str]`)."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CardRow(Base):
    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    board_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    column_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    tags: Mapped[str] = mapped_column(String, nullable=False, default="[]")
