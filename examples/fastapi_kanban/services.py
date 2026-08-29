import uuid

from validator_gateway import (
    ConflictError,
    NotFoundError,
    UpstreamServiceError,
    ValidationFailedError,
)

from .models import BoardOut, BoardSummary, CardOut, ColumnOut

DEFAULT_COLUMNS = ["To Do", "In Progress", "Done"]

# Deliberately small, so it's easy to test the validation-error path (both
# the backend rejecting it and the frontend displaying that rejection)
# without having to type a paragraph first.
MAX_CARD_TITLE_LENGTH = 10


class _Card:
    __slots__ = ("id", "title", "description", "column_id")

    def __init__(self, id: str, title: str, description: str, column_id: str) -> None:
        self.id = id
        self.title = title
        self.description = description
        self.column_id = column_id


class _Column:
    __slots__ = ("id", "name")

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name


class _Board:
    __slots__ = ("id", "name", "columns", "column_order", "cards")

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name
        self.columns: dict[str, _Column] = {}
        self.column_order: list[str] = []
        self.cards: dict[str, _Card] = {}


class KanbanService:
    """Fake in-memory repository + business logic. Raises validator_gateway
    DomainError subclasses — it knows nothing about HTTP or the gateway."""

    def __init__(self) -> None:
        self._boards: dict[str, _Board] = {}
        self._simulate_db_error = False

    def set_simulate_db_error(self, enabled: bool) -> None:
        """Test-only knob: while enabled, every method below raises
        UpstreamServiceError before touching any data, standing in for a
        real "the database connection is down" failure. Flipped via
        POST /api/debug/db-connection — see main.py."""
        self._simulate_db_error = enabled

    def _check_db_connection(self) -> None:
        if self._simulate_db_error:
            raise UpstreamServiceError("Database connection failed (simulated)")

    # --- boards (the "boards" list feature) ---

    async def create_board(self, name: str) -> BoardOut:
        self._check_db_connection()
        if not name.strip():
            raise ValidationFailedError("Board name must not be empty")
        board = _Board(id=str(uuid.uuid4()), name=name)
        for column_name in DEFAULT_COLUMNS:
            self._add_column(board, column_name)
        self._boards[board.id] = board
        return self._to_board_out(board)

    async def list_boards(self) -> list[BoardSummary]:
        self._check_db_connection()
        return [
            BoardSummary(
                id=board.id,
                name=board.name,
                column_count=len(board.columns),
                card_count=len(board.cards),
            )
            for board in self._boards.values()
        ]

    # --- single board (the "board" detail feature) ---

    async def get_board(self, board_id: str) -> BoardOut:
        self._check_db_connection()
        return self._to_board_out(self._require_board(board_id))

    async def delete_board(self, board_id: str) -> None:
        self._check_db_connection()
        board = self._require_board(board_id)
        del self._boards[board.id]

    async def add_column(self, board_id: str, name: str) -> ColumnOut:
        self._check_db_connection()
        board = self._require_board(board_id)
        if not name.strip():
            raise ValidationFailedError("Column name must not be empty")
        if any(column.name == name for column in board.columns.values()):
            raise ConflictError(f"Column {name!r} already exists on this board")
        column = self._add_column(board, name)
        return ColumnOut(id=column.id, name=column.name, cards=[])

    async def delete_column(self, board_id: str, column_id: str) -> None:
        self._check_db_connection()
        board = self._require_board(board_id)
        column = self._require_column(board, column_id)
        card_count = sum(1 for card in board.cards.values() if card.column_id == column_id)
        if card_count:
            raise ConflictError(
                f"Column {column.name!r} still has {card_count} card(s) "
                "— move or delete them first"
            )
        board.column_order.remove(column_id)
        del board.columns[column_id]

    async def create_card(
        self, board_id: str, column_id: str, title: str, description: str
    ) -> CardOut:
        self._check_db_connection()
        board = self._require_board(board_id)
        self._require_column(board, column_id)
        self._validate_title(title)
        card = _Card(
            id=str(uuid.uuid4()), title=title, description=description, column_id=column_id
        )
        board.cards[card.id] = card
        return self._to_card_out(card)

    async def update_card(
        self, card_id: str, title: str | None, description: str | None
    ) -> CardOut:
        self._check_db_connection()
        _, card = self._require_card(card_id)
        if title is not None:
            self._validate_title(title)
            card.title = title
        if description is not None:
            card.description = description
        return self._to_card_out(card)

    async def move_card(self, card_id: str, column_id: str) -> CardOut:
        self._check_db_connection()
        board, card = self._require_card(card_id)
        self._require_column(board, column_id)
        card.column_id = column_id
        return self._to_card_out(card)

    async def delete_card(self, card_id: str) -> None:
        self._check_db_connection()
        board, card = self._require_card(card_id)
        del board.cards[card.id]

    # --- helpers ---

    def _validate_title(self, title: str) -> None:
        if not title.strip():
            raise ValidationFailedError("Card title must not be empty")
        if len(title) > MAX_CARD_TITLE_LENGTH:
            raise ValidationFailedError(
                f"Card title must be at most {MAX_CARD_TITLE_LENGTH} characters "
                f"(got {len(title)})"
            )

    def _add_column(self, board: _Board, name: str) -> _Column:
        column = _Column(id=str(uuid.uuid4()), name=name)
        board.columns[column.id] = column
        board.column_order.append(column.id)
        return column

    def _require_board(self, board_id: str) -> _Board:
        board = self._boards.get(board_id)
        if board is None:
            raise NotFoundError(f"Board {board_id} not found")
        return board

    def _require_column(self, board: _Board, column_id: str) -> _Column:
        column = board.columns.get(column_id)
        if column is None:
            raise NotFoundError(f"Column {column_id} not found on board {board.id}")
        return column

    def _require_card(self, card_id: str) -> tuple[_Board, _Card]:
        for board in self._boards.values():
            card = board.cards.get(card_id)
            if card is not None:
                return board, card
        raise NotFoundError(f"Card {card_id} not found")

    def _to_card_out(self, card: _Card) -> CardOut:
        return CardOut(
            id=card.id, title=card.title, description=card.description, column_id=card.column_id
        )

    def _to_board_out(self, board: _Board) -> BoardOut:
        columns_out = []
        for column_id in board.column_order:
            column = board.columns[column_id]
            cards = [
                self._to_card_out(card)
                for card in board.cards.values()
                if card.column_id == column_id
            ]
            columns_out.append(ColumnOut(id=column.id, name=column.name, cards=cards))
        return BoardOut(id=board.id, name=board.name, columns=columns_out)
