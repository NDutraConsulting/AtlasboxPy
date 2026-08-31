import pytest
from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel

from atlasboxpy_controller.exceptions import ConflictError, NotFoundError
from atlasboxpy_controller.fastapi_integration import (
    apply_registry_to_route,
    build_custom_openapi,
    iter_api_routes,
)
from atlasboxpy_controller.registry import ModelRegistry


class CreateUserRequest(BaseModel):
    name: str


# --- P7-T1: ModelRegistry ---


def test_register_and_get():
    registry = ModelRegistry()
    registry.register("POST", "/users", CreateUserRequest)
    registration = registry.get("post", "/users")  # case-insensitive method
    assert registration is not None
    assert registration.model is CreateUserRequest


def test_register_used_as_a_decorator():
    registry = ModelRegistry()

    @registry.register("POST", "/users", CreateUserRequest)
    async def create_user(payload: CreateUserRequest):
        return payload

    assert registry.get("POST", "/users").model is CreateUserRequest
    assert create_user.__name__ == "create_user"


def test_duplicate_registration_without_overwrite_raises():
    registry = ModelRegistry()
    registry.register("POST", "/users", CreateUserRequest)

    class OtherModel(BaseModel):
        x: int

    with pytest.raises(ValueError, match="already registered"):
        registry.register("POST", "/users", OtherModel)


def test_duplicate_registration_with_overwrite_replaces():
    registry = ModelRegistry()
    registry.register("POST", "/users", CreateUserRequest)

    class OtherModel(BaseModel):
        x: int

    registry.register("POST", "/users", OtherModel, overwrite=True)
    assert registry.get("POST", "/users").model is OtherModel


def test_unregistered_lookup_returns_none():
    registry = ModelRegistry()
    assert registry.get("GET", "/nope") is None


def test_reset_clears_registrations():
    registry = ModelRegistry()
    registry.register("POST", "/users", CreateUserRequest)
    registry.reset()
    assert registry.get("POST", "/users") is None


def test_iter_api_routes_finds_routes_through_include_router():
    app = FastAPI()
    router = APIRouter()

    @router.get("/nested")
    async def nested():
        return {}

    app.include_router(router)
    paths = {route.path for route in iter_api_routes(app.routes)}
    assert "/nested" in paths


def test_apply_registry_to_route_skips_head_and_unregistered_routes():
    registry = ModelRegistry()  # deliberately empty

    app = FastAPI()
    router = APIRouter()

    @router.api_route("/thing", methods=["GET", "HEAD", "OPTIONS"])
    async def thing():
        return {}

    app.include_router(router)
    for route in iter_api_routes(app.routes):
        apply_registry_to_route(route, registry)
        # No matching registration for any method, and HEAD/OPTIONS are
        # skipped outright: nothing should have been injected.
        assert not route.openapi_extra


# --- P7-T2: apply_registry_to_route (Level 2) ---


def test_apply_registry_to_route_injects_request_body_schema():
    registry = ModelRegistry()
    registry.register("POST", "/users", CreateUserRequest)

    app = FastAPI()
    router = APIRouter()

    # Body param typed as raw Request — FastAPI can't introspect a shape
    # from it, so nothing auto-generates a requestBody to collide with ours.
    @router.post("/users")
    async def create_user(request: Request):
        return {"ok": True}

    app.include_router(router)
    for route in iter_api_routes(app.routes):
        apply_registry_to_route(route, registry)

    schema = app.openapi()
    request_body = schema["paths"]["/users"]["post"]["requestBody"]
    assert request_body["content"]["application/json"]["schema"] == (
        CreateUserRequest.model_json_schema()
    )


# --- P7-T4: error response schemas via apply_registry_to_route ---


def test_apply_registry_to_route_documents_raises_as_error_responses():
    registry = ModelRegistry()
    registry.register(
        "GET", "/users/{user_id}", CreateUserRequest, raises=[NotFoundError, ConflictError]
    )

    app = FastAPI()
    router = APIRouter()

    @router.get("/users/{user_id}")
    async def get_user(user_id: str):
        return {"id": user_id}

    app.include_router(router)
    for route in iter_api_routes(app.routes):
        apply_registry_to_route(route, registry)

    schema = app.openapi()
    responses = schema["paths"]["/users/{user_id}"]["get"]["responses"]
    assert "404" in responses
    assert "409" in responses
    from atlasboxpy_controller.responses import ErrorResponse

    error_schema = ErrorResponse.model_json_schema()
    assert responses["404"]["content"]["application/json"]["schema"] == error_schema
    assert responses["409"]["content"]["application/json"]["schema"] == error_schema


# --- P7-T3: build_custom_openapi (Level 3) dedupes shared submodels ---


def test_build_custom_openapi_dedupes_shared_submodel():
    class Address(BaseModel):
        street: str

    class UserOut(BaseModel):
        name: str
        address: Address

    class OrgOut(BaseModel):
        title: str
        address: Address

    registry = ModelRegistry()
    registry.register("GET", "/users/{id}", UserOut)
    registry.register("GET", "/orgs/{id}", OrgOut)

    app = FastAPI()
    schema = build_custom_openapi(app, registry)

    schemas = schema["components"]["schemas"]
    assert "Address" in schemas
    assert "UserOut" in schemas
    assert "OrgOut" in schemas
    # Only one Address entry, not "Address" + "Address1" from a ref collision.
    assert sum(1 for name in schemas if name.startswith("Address")) == 1
    assert schemas["UserOut"]["properties"]["address"] == {
        "$ref": "#/components/schemas/Address"
    }
    assert schemas["OrgOut"]["properties"]["address"] == {"$ref": "#/components/schemas/Address"}


def test_build_custom_openapi_produces_valid_looking_openapi_document():
    registry = ModelRegistry()
    registry.register("POST", "/users", CreateUserRequest)

    app = FastAPI(title="Test API", version="1.2.3")
    schema = build_custom_openapi(app, registry)

    assert schema["info"]["title"] == "Test API"
    assert schema["info"]["version"] == "1.2.3"
    assert schema["openapi"].startswith("3.")
    assert "paths" in schema
    assert "CreateUserRequest" in schema["components"]["schemas"]
