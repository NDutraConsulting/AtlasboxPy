import logging

import pytest

from atlasboxpy_service import BaseService


class UserService(BaseService):
    def __init__(self):
        super().__init__()
        self.calls: list[str] = []

    async def get_user(self, user_id: str):
        self.calls.append(user_id)
        if user_id == "boom":
            raise ValueError("kaboom")
        return {"id": user_id}

    async def _helper(self, user_id: str) -> str:
        """Leading-underscore methods must never be auto-wrapped."""
        return user_id


async def test_success_returns_the_real_value_untouched():
    result = await UserService().get_user("123")
    assert result == {"id": "123"}


async def test_unexpected_exception_is_logged_and_reraised():
    with pytest.raises(ValueError, match="kaboom"):
        await UserService().get_user("boom")


async def test_leading_underscore_methods_are_not_wrapped(caplog):
    with caplog.at_level(logging.INFO, logger=UserService.__module__):
        result = await UserService()._helper("123")
    assert result == "123"
    assert not any("service_call" in r.getMessage() for r in caplog.records)


async def test_success_is_logged_at_info_with_call_and_outcome(caplog):
    with caplog.at_level(logging.INFO, logger=UserService.__module__):
        await UserService().get_user("123")

    messages = [r.getMessage() for r in caplog.records]
    assert any("method=get_user" in m and "args=" in m for m in messages)
    assert any("method=get_user" in m and "status=ok" in m for m in messages)
    assert all(r.levelno == logging.INFO for r in caplog.records)


async def test_failure_is_logged_at_error_with_traceback(caplog):
    with caplog.at_level(logging.INFO, logger=UserService.__module__):
        with pytest.raises(ValueError):
            await UserService().get_user("boom")

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    assert "status=error" in error_records[0].getMessage()
    assert error_records[0].exc_info is not None


async def test_large_args_and_results_are_truncated_in_the_log(caplog):
    class BigService(BaseService):
        async def echo(self, payload: str) -> str:
            return payload

    huge = "x" * 5000
    with caplog.at_level(logging.INFO, logger=BigService.__module__):
        await BigService().echo(huge)

    for record in caplog.records:
        assert len(record.getMessage()) < 1000


async def test_subclass_override_gets_its_own_independent_wrapping(caplog):
    class Base(BaseService):
        async def get_thing(self, thing_id: str):
            return {"id": thing_id, "layer": "base"}

    class Child(Base):
        async def get_thing(self, thing_id: str):
            return {"id": thing_id, "layer": "child"}

    base_result = await Base().get_thing("1")
    assert base_result == {"id": "1", "layer": "base"}

    child_result = await Child().get_thing("1")
    assert child_result == {"id": "1", "layer": "child"}


async def test_custom_logger_can_be_injected():
    custom_logger = logging.getLogger("my.custom.logger")

    class Service(BaseService):
        async def ping(self) -> str:
            return "pong"

    service = Service(logger=custom_logger)
    assert service.logger is custom_logger
    assert await service.ping() == "pong"


async def test_default_logger_is_named_after_the_module():
    class Service(BaseService):
        async def ping(self) -> str:
            return "pong"

    service = Service()
    assert service.logger.name == Service.__module__
