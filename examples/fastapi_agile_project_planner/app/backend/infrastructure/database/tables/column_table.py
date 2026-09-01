"""The `columns` table — schema only, no query logic. See
infrastructure/database/orm_models/column_orm_model.py for the class
that actually queries this."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ColumnRow(Base):
    __tablename__ = "columns"
    __table_args__ = (UniqueConstraint("board_id", "name", name="uq_columns_board_id_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
