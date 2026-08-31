import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from atlasboxpy_controller.controller import BaseController
from atlasboxpy_controller.exceptions import ConflictError, NotFoundError
from atlasboxpy_controller.fastapi_integration import (
    DomainErrorRoute,
    extract_patch_data,
    to_json_response,
)
from atlasboxpy_controller.responses import SuccessResponse, build_error_response


class UserController(BaseController):
    async def get_user(self, user_id: str):
        if user_id == "missing":
            raise NotFoundError(f"User {user_id} not found")
        return {"id": user_id}


def build_app() -> FastAPI:
    app = FastAPI()
    router = APIRouter()
    controller = UserController()

    @router.get("/users/{user_id}")
    async def get_user(user_id: str):
        result = await controller.get_user(user_id)
        return to_json_response(result)

    app.include_router(router)
    return app


def test_end_to_end_success_and_404_via_testclient():
    client = TestClient(build_app())

    ok = client.get("/users/123")
    assert ok.status_code == 200
    assert ok.json() == {"status": "success", "data": {"id": "123"}}

    missing = client.get("/users/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_to_json_response_success_is_200():
    resp = to_json_response(SuccessResponse(data={"id": "1"}))
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "exc, expected_status",
    [
        (NotFoundError("x"), 404),
        (ConflictError("x"), 409),
    ],
)
def test_to_json_response_error_maps_correct_status(exc, expected_status):
    resp = to_json_response(build_error_response(exc))
    assert resp.status_code == expected_status


def test_domain_error_route_catches_domain_error_bypassing_the_controller():
    app = FastAPI()
    router = APIRouter(route_class=DomainErrorRoute)

    @router.get("/boom")
    async def boom():
        raise NotFoundError("raised directly in the route, not via a controller")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/boom")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_plain_api_route_does_not_catch_a_bypassing_domain_error():
    app = FastAPI()
    router = APIRouter()  # default APIRoute, no DomainErrorRoute

    @router.get("/boom")
    async def boom():
        raise NotFoundError("raised directly in the route, not via a controller")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.headers["content-type"] != "application/json"


def test_extract_patch_data_only_includes_explicitly_set_fields():
    class PatchModel(BaseModel):
        name: str | None = None
        age: int | None = None

    payload = PatchModel(name=None)  # name explicitly set to None, age omitted
    data = extract_patch_data(payload)
    assert data == {"name": None}
    assert "age" not in data
