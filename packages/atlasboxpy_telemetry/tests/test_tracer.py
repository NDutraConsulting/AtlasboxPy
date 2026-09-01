import asyncio
import logging

import pytest

from atlasboxpy_telemetry import (
    Tracer,
    get_current_span_id,
    get_current_trace_id,
    trace_override,
)


@pytest.fixture(autouse=True)
def _telemetry_enabled():
    """Every test in this file exercises span *content*, so force
    telemetry on via the per-request override rather than depending on
    ATLASBOXPY_TELEMETRY_ENABLED being set in the environment."""
    token = trace_override.set(True)
    yield
    trace_override.reset(token)


async def test_span_logs_one_line_with_trace_and_span_ids(caplog):
    tracer = Tracer()
    with caplog.at_level(logging.INFO, logger="atlasboxpy_telemetry"):
        async with tracer.span("do_thing", board_id="b1"):
            pass

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "name=do_thing" in message
    assert "outcome=ok" in message
    assert "trace_id=" in message
    assert "parent_span_id=None" in message  # top-level span, no parent
    assert "'board_id': 'b1'" in message


async def test_span_outside_any_context_gets_a_fresh_trace_id_each_time():
    tracer = Tracer()
    async with tracer.span("first") as span_a:
        pass
    async with tracer.span("second") as span_b:
        pass
    assert span_a.trace_id != span_b.trace_id


async def test_nested_span_shares_trace_id_and_records_correct_parent():
    tracer = Tracer()
    async with tracer.span("outer") as outer:
        async with tracer.span("inner") as inner:
            pass

    assert inner.trace_id == outer.trace_id
    assert inner.parent_span_id == outer.span_id
    assert outer.parent_span_id is None


async def test_current_span_and_trace_are_reset_after_the_block_exits():
    tracer = Tracer()
    assert get_current_trace_id() is None
    assert get_current_span_id() is None

    async with tracer.span("thing"):
        assert get_current_trace_id() is not None
        assert get_current_span_id() is not None

    assert get_current_trace_id() is None
    assert get_current_span_id() is None


async def test_exception_inside_a_span_is_logged_as_error_outcome_and_reraised(caplog):
    tracer = Tracer()
    with caplog.at_level(logging.INFO, logger="atlasboxpy_telemetry"):
        with pytest.raises(ValueError, match="kaboom"):
            async with tracer.span("boom"):
                raise ValueError("kaboom")

    assert len(caplog.records) == 1
    assert "outcome=error" in caplog.records[0].getMessage()


async def test_disabled_telemetry_emits_no_log_lines(caplog):
    trace_override.set(False)
    tracer = Tracer()
    with caplog.at_level(logging.INFO, logger="atlasboxpy_telemetry"):
        async with tracer.span("do_thing"):
            pass
    assert caplog.records == []


async def test_disabled_telemetry_still_tracks_span_nesting_correctly():
    """Logging is skipped when disabled, but the context bookkeeping
    (trace_id/parent tracking) still runs — cheap, and means re-enabling
    mid-chain (not a real scenario today, but not something to design a
    special case against) wouldn't see broken parent tracking."""
    trace_override.set(False)
    tracer = Tracer()
    async with tracer.span("outer") as outer:
        async with tracer.span("inner") as inner:
            pass
    assert inner.parent_span_id == outer.span_id
    assert inner.trace_id == outer.trace_id


async def test_concurrent_tasks_do_not_share_trace_or_span_state():
    tracer = Tracer()
    observed: dict[str, tuple[str, str | None]] = {}

    async def run(label: str) -> None:
        async with tracer.span(label) as span:
            await asyncio.sleep(0.01)  # yield control — a sibling task runs here
            observed[label] = (get_current_trace_id() or "", get_current_span_id())
            assert observed[label][1] == span.span_id

    await asyncio.gather(run("task-a"), run("task-b"))

    assert observed["task-a"][0] != observed["task-b"][0]  # different trace ids
    assert observed["task-a"][1] != observed["task-b"][1]  # different span ids


async def test_an_attribute_literally_named_name_does_not_collide():
    """span_name is positional-only specifically so a caller's own
    attribute named "name" — one of the most common field names in any
    codebase — can never collide with it and raise
    "got multiple values for argument 'name'"."""
    tracer = Tracer()
    async with tracer.span("add_column", name="Backlog") as span:
        pass
    assert span.name == "add_column"
    assert span.attributes == {"name": "Backlog"}
