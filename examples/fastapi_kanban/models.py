"""Request DTOs — the shapes the "validation" layer (validation.py) checks
incoming JSON bodies against, before a route ever calls the gateway.
Response shapes are plain dicts assembled by KanbanController; there's no
dedicated output model layer in this demo."""

from pydantic import BaseModel


class CreateBoardRequest(BaseModel):
    name: str


class CreateColumnRequest(BaseModel):
    name: str


class CreateCardRequest(BaseModel):
    column_id: str
    title: str
    description: str = ""


class UpdateCardRequest(BaseModel):
    title: str | None = None
    description: str | None = None


class MoveCardRequest(BaseModel):
    column_id: str


class SimulateDbErrorRequest(BaseModel):
    enabled: bool
    mode: str = "error"  # "error" or "timeout"
