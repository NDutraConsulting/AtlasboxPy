"""The `cards` table — schema only, no query logic. See
infrastructure/database/orm_models/card_orm_model.py for the class that
actually queries this.

Deliberately denormalizes `board_id` alongside `column_id` (rather than
requiring a join through `columns`) so a card query never needs to know
the `columns`/`boards` schema at all — it only ever queries its own
`cards` table, filtered/grouped by the ids it's given."""

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
