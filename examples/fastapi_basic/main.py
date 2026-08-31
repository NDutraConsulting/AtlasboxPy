"""Minimal but complete CRUD example built on atlasboxpy_controller.

Run it with:
    pip install -e "packages/atlasboxpy_controller[fastapi]"
    uvicorn examples.fastapi_basic.main:app --reload

Then, e.g.:
    curl -X POST localhost:8000/users -d '{"name": "Ada", "email": "ada@example.com"}' \
        -H 'content-type: application/json'
    curl localhost:8000/users/<id-from-above>
    curl localhost:8000/users/does-not-exist   # -> formatted 404 ErrorResponse

Routes call the controller directly — BaseController wraps every public
async method, so `await controller.create_user(payload)` already returns a
SuccessResponse/ErrorResponse. No gateway object, no Depends() plumbing.
"""

from fastapi import APIRouter, FastAPI, Request

from atlasboxpy_controller import AlreadyExistsError
from atlasboxpy_controller.fastapi_integration import (
    apply_registry_to_route,
    iter_api_routes,
    to_json_response,
)
from atlasboxpy_controller.registry import ModelRegistry

from .controllers import UserController
from .models import CreateUserRequest, UpdateUserRequest
from .services import UserService

service = UserService()
controller = UserController(service)
registry = ModelRegistry()

app = FastAPI(title="atlasboxpy_controller — fastapi_basic example")
router = APIRouter()


# --- Level 1 integration: typed signatures, FastAPI introspects everything ---


@router.post("/users")
async def create_user(payload: CreateUserRequest):
    result = await controller.create_user(payload)
    return to_json_response(result)


@router.get("/users/{user_id}")
async def get_user(user_id: str):
    result = await controller.get_user(user_id)
    return to_json_response(result)


@router.get("/users")
async def list_users():
    result = await controller.list_users()
    return to_json_response(result)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, payload: UpdateUserRequest):
    # UserService.update_user uses fastapi_integration.extract_patch_data
    # internally (see services.py) to apply only the fields the client
    # actually set, not every field on UpdateUserRequest.
    result = await controller.update_user(user_id, payload)
    return to_json_response(result)


@router.delete("/users/{user_id}")
async def delete_user(user_id: str):
    result = await controller.delete_user(user_id)
    return to_json_response(result)


# --- Level 2/3 integration: a thin route FastAPI can't introspect on its ---
# --- own, documented via the ModelRegistry instead                      ---

registry.register("POST", "/users/thin", CreateUserRequest, raises=[AlreadyExistsError])


@router.post("/users/thin")
async def create_user_thin(request: Request):
    payload = CreateUserRequest.model_validate(await request.json())
    result = await controller.create_user(payload)
    return to_json_response(result)


app.include_router(router)

for route in iter_api_routes(app.routes):
    apply_registry_to_route(route, registry)
