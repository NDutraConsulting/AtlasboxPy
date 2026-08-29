"""Kanban demo: a validator_gateway backend plus a static, DDD-organized
frontend — one folder per feature/page, each holding its own CSS and a
{feature}-controller.js that orchestrates {feature}-api.js + {feature}-ui.js.

Backend layout mirrors the same convention: controllers/ and
validator_gateways/ are directories, one file per feature (matching
`validator-gateway init`'s scaffold). Each api_route below constructs a
fresh instance of the feature's own *ValidatorGateway subclass — e.g.
BoardValidatorGateway — passing it a SourceJson that declares exactly who
is calling (this route's real URL and REST method, plus "api_route" as the
caller type). That gateway subclass then constructs and wraps its own
controller (e.g. BoardController) and owns its own failure-classification
and logging — see validator_gateways/board_validator_gateway.py for where
all of that actually lives.

Run it with:
    pip install -e ".[fastapi]"
    uvicorn examples.fastapi_kanban.main:app --reload
(or just ./run.sh from this directory)

Then open http://127.0.0.1:8000/ in a browser. Every request that moves
across a gateway below is logged to logs/{YYYY-mm-dd}_validator_gateway.log
— see logging_setup.py.
"""

from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from validator_gateway.fastapi_integration import to_json_response

from .models import (
    CreateBoardRequest,
    CreateCardRequest,
    CreateColumnRequest,
    MoveCardRequest,
    SimulateDbErrorRequest,
    UpdateCardRequest,
)
from .services import KanbanService
from .validator_gateways import BoardValidatorGateway, BoardsValidatorGateway, SourceJson

service = KanbanService()

app = FastAPI(title="validator_gateway — Kanban example")
router = APIRouter(prefix="/api")


def _source_json(request: Request) -> SourceJson:
    return SourceJson(url=request.url.path, method=request.method, caller_type="api_route")


@router.post("/boards")
async def create_board(payload: CreateBoardRequest, request: Request):
    gateway = BoardsValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.create_board, payload)
    return to_json_response(result)


@router.get("/boards")
async def list_boards(request: Request):
    gateway = BoardsValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.list_boards)
    return to_json_response(result)


@router.get("/boards/{board_id}")
async def get_board(board_id: str, request: Request):
    gateway = BoardValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.get_board, board_id)
    return to_json_response(result)


@router.delete("/boards/{board_id}")
async def delete_board(board_id: str, request: Request):
    gateway = BoardValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.delete_board, board_id)
    return to_json_response(result)


@router.post("/boards/{board_id}/columns")
async def add_column(board_id: str, payload: CreateColumnRequest, request: Request):
    gateway = BoardValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.add_column, board_id, payload)
    return to_json_response(result)


@router.delete("/boards/{board_id}/columns/{column_id}")
async def delete_column(board_id: str, column_id: str, request: Request):
    gateway = BoardValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.delete_column, board_id, column_id)
    return to_json_response(result)


@router.post("/boards/{board_id}/cards")
async def create_card(board_id: str, payload: CreateCardRequest, request: Request):
    gateway = BoardValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.create_card, board_id, payload)
    return to_json_response(result)


@router.patch("/cards/{card_id}")
async def update_card(card_id: str, payload: UpdateCardRequest, request: Request):
    gateway = BoardValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.update_card, card_id, payload)
    return to_json_response(result)


@router.post("/cards/{card_id}/move")
async def move_card(card_id: str, payload: MoveCardRequest, request: Request):
    gateway = BoardValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.move_card, card_id, payload)
    return to_json_response(result)


@router.delete("/cards/{card_id}")
async def delete_card(card_id: str, request: Request):
    gateway = BoardValidatorGateway(service, source_json=_source_json(request))
    result = await gateway.handle(gateway.controller.delete_card, card_id)
    return to_json_response(result)


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
