import logging

import pytest

from validator_gateway.controller import BaseController
from validator_gateway.exceptions import DomainError, NotFoundError
from validator_gateway.gateway import ValidatorGateway
from validator_gateway.logging import chain_hooks, default_logging_hook


class Controller(BaseController):
    async def not_found(self):
        raise NotFoundError("missing")

    async def boom(self):
        raise ValueError("kaboom")


@pytest.mark.asyncio
async def test_default_logging_hook_logs_domain_error_at_warning(caplog):
    controller = Controller()
    gateway = ValidatorGateway(controller, on_exception=default_logging_hook())
    with caplog.at_level(logging.WARNING, logger="validator_gateway"):
        await gateway.handle(gateway.controller.not_found)
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.asyncio
async def test_default_logging_hook_logs_unexpected_error_at_error(caplog):
    controller = Controller()
    gateway = ValidatorGateway(controller, on_exception=default_logging_hook())
    with caplog.at_level(logging.WARNING, logger="validator_gateway"):
        await gateway.handle(gateway.controller.boom)
    assert any(record.levelno == logging.ERROR for record in caplog.records)


def test_chain_hooks_calls_both_in_order():
    calls = []
    hook_a = lambda exc: calls.append("a")  # noqa: E731
    hook_b = lambda exc: calls.append("b")  # noqa: E731

    chain_hooks(hook_a, hook_b)(NotFoundError())
    assert calls == ["a", "b"]


def test_chain_hooks_survives_a_failing_hook(caplog):
    calls = []

    def hook_a(exc: DomainError) -> None:
        raise RuntimeError("hook blew up")

    def hook_b(exc: DomainError) -> None:
        calls.append("b")

    with caplog.at_level(logging.ERROR, logger="validator_gateway"):
        chain_hooks(hook_a, hook_b)(NotFoundError())

    assert calls == ["b"]
    assert any(record.levelno == logging.ERROR for record in caplog.records)


@pytest.mark.asyncio
async def test_hook_failure_never_breaks_handle(caplog):
    def bad_hook(exc: DomainError) -> None:
        raise RuntimeError("hook blew up")

    controller = Controller()
    gateway = ValidatorGateway(controller, on_exception=chain_hooks(bad_hook))
    resp = await gateway.handle(gateway.controller.not_found)
    assert resp.error.code == "not_found"
