import pytest

from validator_gateway.controller import BaseController
from validator_gateway.exceptions import NotFoundError
from validator_gateway.gateway import ValidatorGateway
from validator_gateway.responses import ErrorResponse, SuccessResponse


class UserController(BaseController):
    def __init__(self):
        super().__init__()
        self.calls: list[str] = []

    async def get_user(self, user_id: str):
        self.calls.append(user_id)
        if user_id == "missing":
            raise NotFoundError(f"User {user_id} not found")
        if user_id == "boom":
            raise ValueError("kaboom")
        return {"id": user_id}


@pytest.mark.asyncio
async def test_handle_success_returns_success_response():
    controller = UserController()
    gateway = ValidatorGateway(controller)
    resp = await gateway.handle(gateway.controller.get_user, "123")
    assert isinstance(resp, SuccessResponse)
    assert resp.data == {"id": "123"}


@pytest.mark.asyncio
async def test_handle_domain_error_returns_error_response_not_raise():
    controller = UserController()
    gateway = ValidatorGateway(controller)
    resp = await gateway.handle(gateway.controller.get_user, "missing")
    assert isinstance(resp, ErrorResponse)
    assert resp.error.code == "not_found"


@pytest.mark.asyncio
async def test_handle_wraps_unexpected_exception():
    controller = UserController()
    gateway = ValidatorGateway(controller)
    resp = await gateway.handle(gateway.controller.get_user, "boom")
    assert isinstance(resp, ErrorResponse)
    assert resp.error.code == "domain_error"


@pytest.mark.asyncio
async def test_handle_rejects_method_of_a_different_controller():
    controller = UserController()
    other = UserController()
    gateway = ValidatorGateway(controller)

    with pytest.raises(ValueError):
        await gateway.handle(other.get_user, "123")
    assert other.calls == []


@pytest.mark.asyncio
async def test_system_exit_propagates_uncaught():
    class Controller(BaseController):
        async def crash(self):
            raise SystemExit(1)

    controller = Controller()
    gateway = ValidatorGateway(controller)
    with pytest.raises(SystemExit):
        await gateway.handle(gateway.controller.crash)


def test_constructing_with_none_raises_type_error():
    with pytest.raises(TypeError):
        ValidatorGateway(None)


def test_constructing_with_plain_object_raises_type_error():
    with pytest.raises(TypeError):
        ValidatorGateway(object())


def test_constructing_with_class_not_instance_raises_type_error():
    with pytest.raises(TypeError):
        ValidatorGateway(UserController)


def test_constructing_with_sync_only_controller_raises_type_error():
    class SyncOnly:
        def get_user(self, user_id):
            return {"id": user_id}

    with pytest.raises(TypeError):
        ValidatorGateway(SyncOnly())
