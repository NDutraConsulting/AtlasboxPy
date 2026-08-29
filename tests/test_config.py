import pytest

from validator_gateway.config import GatewayConfig
from validator_gateway.controller import BaseController
from validator_gateway.gateway import ValidatorGateway


class Controller(BaseController):
    async def boom(self):
        raise ValueError("internal detail")


def test_defaults_are_safe_for_production():
    config = GatewayConfig()
    assert config.hide_internal_errors is True
    assert config.include_traceback_in_details is False


@pytest.mark.asyncio
async def test_hide_internal_errors_true_masks_message():
    controller = Controller()
    gateway = ValidatorGateway(controller, config=GatewayConfig(hide_internal_errors=True))
    resp = await gateway.handle(controller.boom)
    assert resp.error.message == "An unexpected error occurred."


@pytest.mark.asyncio
async def test_hide_internal_errors_false_surfaces_message():
    controller = Controller()
    gateway = ValidatorGateway(controller, config=GatewayConfig(hide_internal_errors=False))
    resp = await gateway.handle(controller.boom)
    assert resp.error.message == "internal detail"
