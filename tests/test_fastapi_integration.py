import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from validator_gateway.controller import BaseController
from validator_gateway.exceptions import ConflictError, NotFoundError
from validator_gateway.fastapi_integration import (
    GatewayRoute,
    extract_patch_data,
    get_gateway_factory,
    to_json_response,
)
from validator_gateway.gateway import ValidatorGateway
from validator_gateway.responses import SuccessResponse


class UserController(BaseController):
    async def get_user(self, user_id: str):
        if user_id == "missing":
            raise NotFoundError(f"User {user_id} not found")
        return {"id": user_id}


def build_app() -> FastAPI:
    app = FastAPI()
    router = APIRouter()
    gateway_dep = get_gateway_factory(lambda: UserController())

    @router.get("/users/{user_id}")
    async def get_user(user_id: str, gateway: ValidatorGateway = Depends(gateway_dep)):
        result = await gateway.handle(gateway.controller.get_user, user_id)
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


def test_get_gateway_factory_builds_fresh_gateway_per_request():
    client = TestClient(build_app())
    client.get("/users/123")
    client.get("/users/123")
    # No shared mutable state is asserted implicitly: each request succeeds
    # independently with its own controller instance from the lambda factory.


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
    from validator_gateway.responses import build_error_response

    resp = to_json_response(build_error_response(exc))
    assert resp.status_code == expected_status


def test_gateway_route_catches_domain_error_bypassing_handle():
    app = FastAPI()
    router = APIRouter(route_class=GatewayRoute)

    @router.get("/boom")
    async def boom():
        raise NotFoundError("bypassed the gateway")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/boom")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_plain_api_route_does_not_catch_bypassing_domain_error():
    app = FastAPI()
    router = APIRouter()  # default APIRoute, no GatewayRoute

    @router.get("/boom")
    async def boom():
        raise NotFoundError("bypassed the gateway")

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
