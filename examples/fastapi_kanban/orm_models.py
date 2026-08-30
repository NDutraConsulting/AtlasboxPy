"""SQLAlchemy ORM tables — the "models" at the bottom of the layering:
api-route > validation > controller(orchestrates services) >
[services > [libraries, apis, repositories, models]].

CardRow deliberately denormalizes `board_id` alongside `column_id` (rather
than requiring a join through `columns`) so CardService never needs to
know the `columns`/`boards` table schema at all — it only ever queries its
own `cards` table, filtered/grouped by the ids it's given. That's what
keeps BoardService and CardService independent while sharing one SQLite
database: no service reaches into a table it doesn't own.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BoardRow(Base):
    __tablename__ = "boards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)


class ColumnRow(Base):
    __tablename__ = "columns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CardRow(Base):
    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    board_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    column_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
