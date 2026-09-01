"""The `boards` table — schema only, no query logic. See
infrastructure/database/orm_models/board_orm_model.py for the class that
actually queries this."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BoardRow(Base):
    __tablename__ = "boards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
