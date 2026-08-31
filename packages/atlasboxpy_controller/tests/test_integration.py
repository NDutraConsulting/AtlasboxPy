"""A full layered lifecycle — route -> controller -> service -> repository
(in-memory fake) -> back through error/success formatting — for a success
path and one path per major DomainError subclass. Deliberately separate
from examples/, which are runnable demos rather than test fixtures."""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from atlasboxpy_controller.controller import BaseController
from atlasboxpy_controller.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
    RateLimitedError,
    UnauthenticatedError,
    UnprocessableError,
    UpstreamServiceError,
    ValidationFailedError,
)
from atlasboxpy_controller.fastapi_integration import to_json_response


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[str, dict] = {}

    def add(self, user_id: str, name: str) -> dict:
        self._users[user_id] = {"id": user_id, "name": name}
        return self._users[user_id]

    def find(self, user_id: str) -> dict | None:
        return self._users.get(user_id)

    def exists(self, user_id: str) -> bool:
        return user_id in self._users


class UserService:
    def __init__(self, repository: InMemoryUserRepository) -> None:
        self.repository = repository

    async def create_user(self, user_id: str, name: str, *, is_admin: bool = False) -> dict:
        if not name:
            raise ValidationFailedError("name must not be empty")
        if self.repository.exists(user_id):
            raise AlreadyExistsError(f"User {user_id} already exists")
        if user_id == "banned" and not is_admin:
            raise PermissionDeniedError("only an admin may create this user")
        return self.repository.add(user_id, name)

    async def get_user(self, user_id: str, *, authenticated: bool = True) -> dict:
        if not authenticated:
            raise UnauthenticatedError("login required")
        user = self.repository.find(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user

    async def publish_user(self, user_id: str, *, version: int) -> dict:
        user = self.repository.find(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        if version != 1:
            raise PreconditionFailedError("stale version")
        if user_id == "unpublishable":
            raise UnprocessableError("user profile is incomplete")
        return user

    async def sync_user(self, user_id: str) -> dict:
        if user_id == "flaky-upstream":
            raise UpstreamServiceError("directory service unavailable")
        if user_id == "rate-limited":
            raise RateLimitedError("too many syncs")
        user = self.repository.find(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user


class UserController(BaseController):
    def __init__(self, service: UserService) -> None:
        super().__init__()
        self.service = service

    async def create_user(self, user_id: str, name: str) -> dict:
        return await self.service.create_user(user_id, name)

    async def get_user(self, user_id: str) -> dict:
        return await self.service.get_user(user_id)

    async def get_user_unauthenticated(self, user_id: str) -> dict:
        return await self.service.get_user(user_id, authenticated=False)

    async def publish_user(self, user_id: str, version: int) -> dict:
        return await self.service.publish_user(user_id, version=version)

    async def sync_user(self, user_id: str) -> dict:
        return await self.service.sync_user(user_id)

    async def create_banned_user(self, user_id: str, name: str) -> dict:
        return await self.service.create_user(user_id, name, is_admin=False)


def build_app() -> FastAPI:
    repository = InMemoryUserRepository()
    service = UserService(repository)
    controller = UserController(service)
    app = FastAPI()
    router = APIRouter()

    @router.post("/users/{user_id}")
    async def create_user(user_id: str, name: str):
        result = await controller.create_user(user_id, name)
        return to_json_response(result)

    @router.post("/users/{user_id}/banned")
    async def create_banned_user(user_id: str, name: str):
        result = await controller.create_banned_user(user_id, name)
        return to_json_response(result)

    @router.get("/users/{user_id}")
    async def get_user(user_id: str):
        result = await controller.get_user(user_id)
        return to_json_response(result)

    @router.get("/users/{user_id}/unauthenticated")
    async def get_user_unauthenticated(user_id: str):
        result = await controller.get_user_unauthenticated(user_id)
        return to_json_response(result)

    @router.post("/users/{user_id}/publish")
    async def publish_user(user_id: str, version: int):
        result = await controller.publish_user(user_id, version)
        return to_json_response(result)

    @router.post("/users/{user_id}/sync")
    async def sync_user(user_id: str):
        result = await controller.sync_user(user_id)
        return to_json_response(result)

    app.include_router(router)
    return app


def test_success_path_create_then_get():
    client = TestClient(build_app())

    created = client.post("/users/123?name=Ada")
    assert created.status_code == 200
    assert created.json()["data"] == {"id": "123", "name": "Ada"}

    fetched = client.get("/users/123")
    assert fetched.status_code == 200
    assert fetched.json()["data"] == {"id": "123", "name": "Ada"}


def test_validation_failed_returns_422():
    client = TestClient(build_app())
    resp = client.post("/users/123?name=")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"


def test_already_exists_returns_409():
    client = TestClient(build_app())
    client.post("/users/123?name=Ada")
    resp = client.post("/users/123?name=Ada")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already_exists"


def test_not_found_returns_404():
    client = TestClient(build_app())
    resp = client.get("/users/missing")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_permission_denied_returns_403():
    client = TestClient(build_app())
    resp = client.post("/users/banned/banned?name=Eve")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "permission_denied"


def test_unauthenticated_returns_401():
    client = TestClient(build_app())
    resp = client.get("/users/123/unauthenticated")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthenticated"


def test_precondition_failed_returns_412():
    client = TestClient(build_app())
    client.post("/users/123?name=Ada")
    resp = client.post("/users/123/publish?version=2")
    assert resp.status_code == 412
    assert resp.json()["error"]["code"] == "precondition_failed"


def test_unprocessable_returns_422():
    client = TestClient(build_app())
    client.post("/users/unpublishable?name=Ada")
    resp = client.post("/users/unpublishable/publish?version=1")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable"


def test_upstream_error_returns_502():
    client = TestClient(build_app())
    resp = client.post("/users/flaky-upstream/sync")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"


def test_rate_limited_returns_429():
    client = TestClient(build_app())
    resp = client.post("/users/rate-limited/sync")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
