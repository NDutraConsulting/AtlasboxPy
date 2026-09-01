"""The one shared SQLAlchemy declarative registry every table below
attaches to — needed for `Base.metadata.create_all()`
(infrastructure/database/session.py's `init_db`) to create every table
together. A table file imports this, never defines its own `Base`."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
