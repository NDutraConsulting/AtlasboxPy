"""Minimal but complete CRUD example built on validator_gateway.

Run it with:
    pip install -e ".[fastapi]"
    uvicorn examples.fastapi_basic.main:app --reload

Then, e.g.:
    curl -X POST localhost:8000/users -d '{"name": "Ada", "email": "ada@example.com"}' \
        -H 'content-type: application/json'
    curl localhost:8000/users/<id-from-above>
    curl localhost:8000/users/does-not-exist   # -> formatted 404 ErrorResponse

This gateway is constructed WITHOUT `recovery=` — per Design Decision 8, a
synchronous REST route wants fail-fast behavior. See
examples/worker_recovery for the retry/redirect/queue-enabled counterpart.
"""

from fastapi import APIRouter, Depends, FastAPI, Request

from validator_gateway import AlreadyExistsError, ValidatorGateway, default_logging_hook
from validator_gateway.fastapi_integration import (
    apply_registry_to_route,
    get_gateway_factory,
    iter_api_routes,
    to_json_response,
)
from validator_gateway.registry import ModelRegistry

from .controllers import UserController
from .models import CreateUserRequest, UpdateUserRequest
from .services import UserService

service = UserService()
registry = ModelRegistry()

app = FastAPI(title="validator_gateway — fastapi_basic example")
router = APIRouter()

gateway_dep = get_gateway_factory(
    lambda: UserController(service), on_exception=default_logging_hook()
)


# --- Level 1 integration: typed signatures, FastAPI introspects everything ---


@router.post("/users")
async def create_user(
    payload: CreateUserRequest, gateway: ValidatorGateway = Depends(gateway_dep)
):
    result = await gateway.handle(gateway.controller.create_user, payload)
    return to_json_response(result)


@router.get("/users/{user_id}")
async def get_user(user_id: str, gateway: ValidatorGateway = Depends(gateway_dep)):
    result = await gateway.handle(gateway.controller.get_user, user_id)
    return to_json_response(result)


@router.get("/users")
async def list_users(gateway: ValidatorGateway = Depends(gateway_dep)):
    result = await gateway.handle(gateway.controller.list_users)
    return to_json_response(result)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, payload: UpdateUserRequest, gateway: ValidatorGateway = Depends(gateway_dep)
):
    # UserService.update_user uses fastapi_integration.extract_patch_data
    # internally (see services.py) to apply only the fields the client
    # actually set, not every field on UpdateUserRequest.
    result = await gateway.handle(gateway.controller.update_user, user_id, payload)
    return to_json_response(result)


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, gateway: ValidatorGateway = Depends(gateway_dep)):
    result = await gateway.handle(gateway.controller.delete_user, user_id)
    return to_json_response(result)


# --- Level 2/3 integration: a thin route FastAPI can't introspect on its ---
# --- own, documented via the ModelRegistry instead                      ---

registry.register("POST", "/users/thin", CreateUserRequest, raises=[AlreadyExistsError])


@router.post("/users/thin")
async def create_user_thin(request: Request, gateway: ValidatorGateway = Depends(gateway_dep)):
    payload = CreateUserRequest.model_validate(await request.json())
    result = await gateway.handle(gateway.controller.create_user, payload)
    return to_json_response(result)


app.include_router(router)

for route in iter_api_routes(app.routes):
    apply_registry_to_route(route, registry)
