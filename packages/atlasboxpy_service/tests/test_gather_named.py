import asyncio
import logging
import time

import pytest

from atlasboxpy_service import BaseService


class OrchestratingService(BaseService):
    async def orchestrate(self, delay_a: float, delay_b: float) -> dict:
        async def slow_a():
            await asyncio.sleep(delay_a)
            return "a-result"

        async def slow_b():
            await asyncio.sleep(delay_b)
            return "b-result"

        return await self.gather_named(a=slow_a(), b=slow_b())


async def test_gather_named_returns_a_dict_keyed_by_name():
    service = OrchestratingService()
    result = await service.gather_named(
        first=_immediate("x"),
        second=_immediate("y"),
    )
    assert result == {"first": "x", "second": "y"}


async def test_gather_named_runs_calls_concurrently_not_sequentially():
    """Two 0.05s calls run concurrently should take ~0.05s total, not
    ~0.1s — proves gather_named doesn't just await them one after
    another."""
    service = OrchestratingService()
    start = time.monotonic()
    await service.orchestrate(delay_a=0.05, delay_b=0.05)
    elapsed = time.monotonic() - start
    assert elapsed < 0.09  # well under the 0.1s a sequential run would take


async def test_gather_named_propagates_the_first_exception():
    service = OrchestratingService()

    async def boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        await service.gather_named(ok=_immediate("fine"), bad=boom())


async def test_gather_named_logs_each_named_call_individually(caplog):
    service = OrchestratingService()
    with caplog.at_level(logging.INFO, logger=OrchestratingService.__module__):
        await service.gather_named(alpha=_immediate("x"), beta=_immediate("y"))

    messages = [r.getMessage() for r in caplog.records]
    assert any("name=alpha" in m and "status=start" in m for m in messages)
    assert any("name=alpha" in m and "status=ok" in m for m in messages)
    assert any("name=beta" in m and "status=start" in m for m in messages)
    assert any("name=beta" in m and "status=ok" in m for m in messages)


async def test_gather_named_logs_the_failing_call_at_error(caplog):
    service = OrchestratingService()

    async def boom():
        raise ValueError("kaboom")

    with caplog.at_level(logging.INFO, logger=OrchestratingService.__module__):
        with pytest.raises(ValueError):
            await service.gather_named(bad=boom())

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    assert "name=bad" in error_records[0].getMessage()


async def test_gather_named_with_no_calls_returns_an_empty_dict():
    service = OrchestratingService()
    assert await service.gather_named() == {}


async def _immediate(value: str) -> str:
    return value
