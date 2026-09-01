"""Importing this package registers every table on `Base.metadata` —
required before `session.py`'s `init_db()` (`Base.metadata.create_all()`)
runs, since `ColumnRow.board_id`'s `ForeignKey("boards.id")` only
resolves once `BoardRow` is registered on the same metadata."""

from .base import Base
from .board_table import BoardRow
from .card_table import CardRow
from .column_table import ColumnRow

__all__ = ["Base", "BoardRow", "CardRow", "ColumnRow"]
