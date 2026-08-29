"""Kanban demo: a validator_gateway backend plus a static, DDD-organized
frontend — one folder per feature/page, each holding its own CSS and a
{feature}-controller.js that orchestrates {feature}-api.js + {feature}-ui.js.

Run it with:
    pip install -e ".[fastapi]"
    uvicorn examples.fastapi_kanban.main:app --reload

Then open http://127.0.0.1:8000/ in a browser.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from validator_gateway import ValidatorGateway, default_logging_hook
from validator_gateway.fastapi_integration import get_gateway_factory, to_json_response

from .controllers import BoardController, BoardsController
from .models import (
    CreateBoardRequest,
    CreateCardRequest,
    CreateColumnRequest,
    MoveCardRequest,
    UpdateCardRequest,
)
from .services import KanbanService

service = KanbanService()

app = FastAPI(title="validator_gateway — Kanban example")
router = APIRouter(prefix="/api")

# Two gateways, matching the two frontend features/pages — both fail-fast
# (no recovery=), per Design Decision 8, since these are synchronous
# request/response calls with a client waiting.
boards_gateway_dep = get_gateway_factory(
    lambda: BoardsController(service), on_exception=default_logging_hook()
)
board_gateway_dep = get_gateway_factory(
    lambda: BoardController(service), on_exception=default_logging_hook()
)


@router.post("/boards")
async def create_board(
    payload: CreateBoardRequest, gateway: ValidatorGateway = Depends(boards_gateway_dep)
):
    result = await gateway.handle(gateway.controller.create_board, payload)
    return to_json_response(result)


@router.get("/boards")
async def list_boards(gateway: ValidatorGateway = Depends(boards_gateway_dep)):
    result = await gateway.handle(gateway.controller.list_boards)
    return to_json_response(result)


@router.get("/boards/{board_id}")
async def get_board(board_id: str, gateway: ValidatorGateway = Depends(board_gateway_dep)):
    result = await gateway.handle(gateway.controller.get_board, board_id)
    return to_json_response(result)


@router.delete("/boards/{board_id}")
async def delete_board(board_id: str, gateway: ValidatorGateway = Depends(board_gateway_dep)):
    result = await gateway.handle(gateway.controller.delete_board, board_id)
    return to_json_response(result)


@router.post("/boards/{board_id}/columns")
async def add_column(
    board_id: str,
    payload: CreateColumnRequest,
    gateway: ValidatorGateway = Depends(board_gateway_dep),
):
    result = await gateway.handle(gateway.controller.add_column, board_id, payload)
    return to_json_response(result)


@router.delete("/boards/{board_id}/columns/{column_id}")
async def delete_column(
    board_id: str, column_id: str, gateway: ValidatorGateway = Depends(board_gateway_dep)
):
    result = await gateway.handle(gateway.controller.delete_column, board_id, column_id)
    return to_json_response(result)


@router.post("/boards/{board_id}/cards")
async def create_card(
    board_id: str, payload: CreateCardRequest, gateway: ValidatorGateway = Depends(board_gateway_dep)
):
    result = await gateway.handle(gateway.controller.create_card, board_id, payload)
    return to_json_response(result)


@router.patch("/cards/{card_id}")
async def update_card(
    card_id: str, payload: UpdateCardRequest, gateway: ValidatorGateway = Depends(board_gateway_dep)
):
    result = await gateway.handle(gateway.controller.update_card, card_id, payload)
    return to_json_response(result)


@router.post("/cards/{card_id}/move")
async def move_card(
    card_id: str, payload: MoveCardRequest, gateway: ValidatorGateway = Depends(board_gateway_dep)
):
    result = await gateway.handle(gateway.controller.move_card, card_id, payload)
    return to_json_response(result)


@router.delete("/cards/{card_id}")
async def delete_card(card_id: str, gateway: ValidatorGateway = Depends(board_gateway_dep)):
    result = await gateway.handle(gateway.controller.delete_card, card_id)
    return to_json_response(result)


app.include_router(router)

# Registered after the API router so /api/* is matched first — the static
# mount at "/" would otherwise greedily swallow every path.
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
