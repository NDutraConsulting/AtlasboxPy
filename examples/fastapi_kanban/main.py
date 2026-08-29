"""Kanban demo: a validator_gateway backend plus a static, DDD-organized
frontend — one folder per feature/page, each holding its own CSS and a
{feature}-controller.js that orchestrates {feature}-api.js + {feature}-ui.js.

Backend layout mirrors the same convention: controllers/ and
validator_gateways/ are directories, one file per feature (matching
`validator-gateway init`'s scaffold). Each api_route below constructs an
instance of the feature's own *ValidatorGateway subclass — e.g.
BoardValidatorGateway — which in turn constructs and wraps its
BoardController. Nothing here builds a bare ValidatorGateway directly.

Run it with:
    pip install -e ".[fastapi]"
    uvicorn examples.fastapi_kanban.main:app --reload
(or just ./run.sh from this directory)

Then open http://127.0.0.1:8000/ in a browser. Every request that moves
across the two gateways below is also logged to
logs/{YYYY-mm-dd}_validator_gateway.log — see logging_setup.py.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from .logging_setup import handle_and_log
from .models import (
    CreateBoardRequest,
    CreateCardRequest,
    CreateColumnRequest,
    MoveCardRequest,
    SimulateDbErrorRequest,
    UpdateCardRequest,
)
from .services import KanbanService
from .validator_gateways.board_validator_gateway import BoardValidatorGateway
from .validator_gateways.boards_validator_gateway import BoardsValidatorGateway

service = KanbanService()

app = FastAPI(title="validator_gateway — Kanban example")
router = APIRouter(prefix="/api")


def get_boards_gateway() -> BoardsValidatorGateway:
    return BoardsValidatorGateway(service, source_info="boards_validator_gateway.py")


def get_board_gateway() -> BoardValidatorGateway:
    return BoardValidatorGateway(service, source_info="board_validator_gateway.py")


@router.post("/boards")
async def create_board(
    payload: CreateBoardRequest, gateway: BoardsValidatorGateway = Depends(get_boards_gateway)
):
    return await handle_and_log(gateway, gateway.controller.create_board, payload)


@router.get("/boards")
async def list_boards(gateway: BoardsValidatorGateway = Depends(get_boards_gateway)):
    return await handle_and_log(gateway, gateway.controller.list_boards)


@router.get("/boards/{board_id}")
async def get_board(board_id: str, gateway: BoardValidatorGateway = Depends(get_board_gateway)):
    return await handle_and_log(gateway, gateway.controller.get_board, board_id)


@router.delete("/boards/{board_id}")
async def delete_board(board_id: str, gateway: BoardValidatorGateway = Depends(get_board_gateway)):
    return await handle_and_log(gateway, gateway.controller.delete_board, board_id)


@router.post("/boards/{board_id}/columns")
async def add_column(
    board_id: str,
    payload: CreateColumnRequest,
    gateway: BoardValidatorGateway = Depends(get_board_gateway),
):
    return await handle_and_log(gateway, gateway.controller.add_column, board_id, payload)


@router.delete("/boards/{board_id}/columns/{column_id}")
async def delete_column(
    board_id: str, column_id: str, gateway: BoardValidatorGateway = Depends(get_board_gateway)
):
    return await handle_and_log(gateway, gateway.controller.delete_column, board_id, column_id)


@router.post("/boards/{board_id}/cards")
async def create_card(
    board_id: str,
    payload: CreateCardRequest,
    gateway: BoardValidatorGateway = Depends(get_board_gateway),
):
    return await handle_and_log(gateway, gateway.controller.create_card, board_id, payload)


@router.patch("/cards/{card_id}")
async def update_card(
    card_id: str,
    payload: UpdateCardRequest,
    gateway: BoardValidatorGateway = Depends(get_board_gateway),
):
    return await handle_and_log(gateway, gateway.controller.update_card, card_id, payload)


@router.post("/cards/{card_id}/move")
async def move_card(
    card_id: str, payload: MoveCardRequest, gateway: BoardValidatorGateway = Depends(get_board_gateway)
):
    return await handle_and_log(gateway, gateway.controller.move_card, card_id, payload)


@router.delete("/cards/{card_id}")
async def delete_card(card_id: str, gateway: BoardValidatorGateway = Depends(get_board_gateway)):
    return await handle_and_log(gateway, gateway.controller.delete_card, card_id)


@router.post("/debug/db-connection")
async def set_db_connection_simulation(payload: SimulateDbErrorRequest) -> dict:
    """Test-only utility — deliberately NOT routed through a
    *ValidatorGateway, unlike every route above. Flipping a boolean isn't
    domain logic, so there's no controller for it; this exists purely so
    you can simulate "the database is down" (every KanbanService call then
    raises UpstreamServiceError) to exercise that failure path on demand,
    e.g.:

        curl -X POST localhost:8000/api/debug/db-connection -d '{"enabled": true}'
        curl -X POST localhost:8000/api/boards -d '{"name": "x"}'   # -> 502
        curl -X POST localhost:8000/api/debug/db-connection -d '{"enabled": false}'
    """
    service.set_simulate_db_error(payload.enabled)
    return {"simulate_db_error": payload.enabled}


app.include_router(router)

# Registered after the API router so /api/* is matched first — the static
# mount at "/" would otherwise greedily swallow every path.
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
