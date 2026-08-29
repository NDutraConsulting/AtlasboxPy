"""P8-T3: adversarial/misuse-style proof of the "can't bypass the gateway"
guarantees from P2-T3 (ValidatorGateway.handle()) and P6-T3 (GatewayRoute)."""

import asyncio

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from validator_gateway.controller import BaseController
from validator_gateway.exceptions import NotFoundError
from validator_gateway.fastapi_integration import GatewayRoute
from validator_gateway.gateway import ValidatorGateway


class ControllerA(BaseController):
    def __init__(self):
        super().__init__()
        self.calls: list[str] = []

    async def get_thing(self, thing_id: str):
        self.calls.append(thing_id)
        return {"id": thing_id}

    def get_thing_sync(self, thing_id: str):
        """A plain synchronous method — not what handle() expects."""
        self.calls.append(thing_id)
        return {"id": thing_id}


class ControllerB(BaseController):
    async def get_thing(self, thing_id: str):
        raise AssertionError("should never be invoked")


def test_handle_refuses_a_different_controllers_bound_method():
    gateway_a = ValidatorGateway(ControllerA())
    controller_b = ControllerB()

    with pytest.raises(ValueError, match="not a method of this gateway's controller"):
        asyncio.run(gateway_a.handle(controller_b.get_thing, "x"))


@pytest.mark.asyncio
async def test_handle_never_invokes_the_wrong_controllers_method():
    controller_a = ControllerA()
    controller_b = ControllerB()
    gateway_a = ValidatorGateway(controller_a)

    with pytest.raises(ValueError):
        await gateway_a.handle(controller_b.get_thing, "x")

    # ControllerB.get_thing would raise AssertionError if it were ever
    # actually called — the ValueError above proves handle() rejected it
    # before invocation, not after a failed call.
    assert controller_a.calls == []


@pytest.mark.asyncio
async def test_handle_wraps_a_sync_method_into_a_formatted_error_not_a_crash():
    """handle() is documented to accept an async bound method of its
    controller. Passing a *sync* one is misuse outside that contract, but
    the single-call-path guarantee still holds: handle() must not let the
    resulting TypeError (awaiting a non-awaitable) escape uncaught — it
    still comes back as a formatted ErrorResponse, never a raw exception."""
    controller = ControllerA()
    gateway = ValidatorGateway(controller)

    resp = await gateway.handle(controller.get_thing_sync, "x")
    assert resp.status == "error"
    assert resp.error.code == "domain_error"


def test_free_function_is_not_checked_against_the_controller():
    """Documented boundary, not a bug: the build plan's own P2-T3 spec scopes
    the different-controller check to "when [__self__] exists" — a bare
    function/lambda has no __self__, so it isn't a "controller method" in
    the first place and the check is skipped entirely. handle()'s contract
    is about controller methods specifically; passing a free function is
    simply outside that documented usage pattern."""
    controller = ControllerA()
    gateway = ValidatorGateway(controller)
    calls = []

    async def free_function(thing_id: str):
        calls.append(thing_id)
        return {"id": thing_id}

    resp = asyncio.run(gateway.handle(free_function, "x"))
    assert resp.status == "success"
    assert calls == ["x"]


@pytest.mark.parametrize("bad_controller", [None, object(), 42, "not a controller"])
def test_constructing_with_invalid_controller_never_yields_a_usable_gateway(bad_controller):
    with pytest.raises(TypeError):
        ValidatorGateway(bad_controller)


def test_constructing_with_the_controller_class_itself_raises():
    with pytest.raises(TypeError, match="instance"):
        ValidatorGateway(ControllerA)


# --- P6-T3: GatewayRoute enforces formatting even when handle() is bypassed ---


def test_gateway_route_enforces_formatting_when_a_handler_bypasses_handle():
    app = FastAPI()
    router = APIRouter(route_class=GatewayRoute)

    @router.get("/bypass")
    async def bypass():
        raise NotFoundError("handler forgot to call gateway.handle()")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/bypass")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_plain_api_route_does_not_enforce_formatting_when_bypassed():
    app = FastAPI()
    router = APIRouter()  # no GatewayRoute — the guarantee does not apply

    @router.get("/bypass")
    async def bypass():
        raise NotFoundError("handler forgot to call gateway.handle()")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/bypass")
    assert resp.status_code == 500
    assert resp.headers["content-type"] != "application/json"
