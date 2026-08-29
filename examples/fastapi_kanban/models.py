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


class CardOut(BaseModel):
    id: str
    title: str
    description: str = ""
    column_id: str


class ColumnOut(BaseModel):
    id: str
    name: str
    cards: list[CardOut] = []


class BoardOut(BaseModel):
    id: str
    name: str
    columns: list[ColumnOut] = []


class BoardSummary(BaseModel):
    id: str
    name: str
    column_count: int
    card_count: int
