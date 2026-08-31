import logging

import pytest

from atlasboxpy_controller.controller import BaseController, ExceptionFormatter
from atlasboxpy_controller.exceptions import DomainError, NotFoundError
from atlasboxpy_controller.responses import (
    ErrorResponse,
    SuccessResponse,
    build_error_response,
)


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

    async def get_user_response(self, user_id: str) -> SuccessResponse | ErrorResponse:
        if user_id == "missing":
            return build_error_response(NotFoundError(f"User {user_id} not found"))
        return SuccessResponse(data={"id": user_id})

    async def _helper(self, user_id: str) -> str:
        """Leading-underscore methods must never be auto-wrapped."""
        return user_id


@pytest.mark.asyncio
async def test_success_returns_success_response():
    resp = await UserController().get_user("123")
    assert isinstance(resp, SuccessResponse)
    assert resp.data == {"id": "123"}


@pytest.mark.asyncio
async def test_raised_domain_error_returns_error_response_not_raise():
    resp = await UserController().get_user("missing")
    assert isinstance(resp, ErrorResponse)
    assert resp.error.code == "not_found"


@pytest.mark.asyncio
async def test_unexpected_exception_is_caught_and_formatted():
    resp = await UserController().get_user("boom")
    assert isinstance(resp, ErrorResponse)
    assert resp.error.code == "domain_error"
    assert resp.error.message == "An unexpected error occurred."


@pytest.mark.asyncio
async def test_unexpected_exception_message_surfaces_when_hide_internal_errors_is_false():
    class Loud(BaseController):
        hide_internal_errors = False

        async def boom(self):
            raise ValueError("internal detail")

    resp = await Loud().boom()
    assert isinstance(resp, ErrorResponse)
    assert resp.error.message == "internal detail"


@pytest.mark.asyncio
async def test_method_can_build_and_return_its_own_response_directly():
    """The preferred style: no exception, no wrapping needed — the method
    already returns a SuccessResponse/ErrorResponse and _wrap passes it
    through untouched."""
    resp = await UserController().get_user_response("missing")
    assert isinstance(resp, ErrorResponse)
    assert resp.error.code == "not_found"

    resp_ok = await UserController().get_user_response("123")
    assert isinstance(resp_ok, SuccessResponse)
    assert resp_ok.data == {"id": "123"}


@pytest.mark.asyncio
async def test_leading_underscore_methods_are_not_wrapped():
    result = await UserController()._helper("123")
    assert result == "123"  # not a SuccessResponse - never wrapped


@pytest.mark.asyncio
async def test_system_exit_propagates_uncaught():
    class Controller(BaseController):
        async def crash(self):
            raise SystemExit(1)

    with pytest.raises(SystemExit):
        await Controller().crash()


@pytest.mark.asyncio
async def test_failure_is_logged_at_warning_for_4xx_and_error_for_5xx(caplog):
    controller = UserController()
    with caplog.at_level(logging.WARNING, logger=UserController.__module__):
        await controller.get_user("missing")
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger=UserController.__module__):
        await controller.get_user("boom")
    assert any(r.levelno == logging.ERROR for r in caplog.records)


@pytest.mark.asyncio
async def test_exception_formatter_has_no_logger_and_skips_logging_silently(caplog):
    """ExceptionFormatter (unlike BaseController) has no self.logger — the
    wrapper must not crash trying to log through one that doesn't exist."""

    class Bare(ExceptionFormatter):
        async def boom(self):
            raise NotFoundError("x")

    with caplog.at_level(logging.WARNING):
        resp = await Bare().boom()
    assert isinstance(resp, ErrorResponse)
    assert resp.error.code == "not_found"


@pytest.mark.asyncio
async def test_subclass_override_gets_its_own_independent_wrapping():
    class Base(BaseController):
        async def get_thing(self, thing_id: str):
            return {"id": thing_id, "layer": "base"}

    class Child(Base):
        async def get_thing(self, thing_id: str):
            if thing_id == "missing":
                raise NotFoundError("nope")
            return {"id": thing_id, "layer": "child"}

    base_resp = await Base().get_thing("1")
    assert base_resp.data == {"id": "1", "layer": "base"}

    child_resp = await Child().get_thing("1")
    assert child_resp.data == {"id": "1", "layer": "child"}

    child_error = await Child().get_thing("missing")
    assert isinstance(child_error, ErrorResponse)


def test_domain_error_raised_directly_is_a_supported_escape_hatch():
    """Not auto-wrapped (sync test, just proving the class hierarchy) —
    DomainError itself remains a plain, raisable Exception subclass."""
    exc = NotFoundError("x")
    assert isinstance(exc, DomainError)
    assert isinstance(exc, Exception)
