"""Request DTOs — each one is the full contract for its KanbanController
method, path params and body fields together. A route never builds one of
these: it merges the request into a plain `props` dict (see main.py's
`_call`, backed by atlasboxpy_controller's `extract_api_request`) and
hands that to the controller method, which validates it into the matching
model here itself, via `validate_props`. Reading a controller method next
to its model tells you exactly what a call needs — the route file has no
opinion on shape at all.

Response shapes are plain dicts assembled by KanbanController; there's no
dedicated output model layer in this demo."""

from pydantic import BaseModel


class CreateBoardRequest(BaseModel):
    name: str


class BoardIdProps(BaseModel):
    """get_board / delete_board — the board_id path param, nothing else."""

    board_id: str


class CreateColumnRequest(BaseModel):
    board_id: str
    name: str


class DeleteColumnProps(BaseModel):
    board_id: str
    column_id: str


class CreateCardRequest(BaseModel):
    board_id: str
    column_id: str
    title: str
    description: str = ""


class UpdateCardRequest(BaseModel):
    card_id: str
    title: str | None = None
    description: str | None = None


class MoveCardRequest(BaseModel):
    card_id: str
    column_id: str


class CardIdProps(BaseModel):
    """delete_card — the card_id path param, nothing else."""

    card_id: str


class SimulateDbErrorRequest(BaseModel):
    enabled: bool
    mode: str = "error"  # "error" or "timeout"
