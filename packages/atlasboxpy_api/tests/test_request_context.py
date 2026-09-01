import asyncio

from atlasboxpy_api import RequestContext


def test_get_returns_default_when_never_set():
    ctx: RequestContext[str] = RequestContext("test-default", default="prod")
    assert ctx.get() == "prod"


def test_set_then_get_returns_the_set_value():
    ctx: RequestContext[str] = RequestContext("test-set", default="prod")
    ctx.set("shadow")
    assert ctx.get() == "shadow"


def test_reset_restores_the_prior_value():
    ctx: RequestContext[str] = RequestContext("test-reset", default="prod")
    token = ctx.set("shadow")
    ctx.reset(token)
    assert ctx.get() == "prod"


async def test_concurrent_tasks_never_see_each_others_value():
    """The whole point of ContextVar over a module-level global: two
    concurrent asyncio tasks each set their own value and must only ever
    observe their own, even though both run "at the same time" on one
    event loop and each awaits partway through."""
    ctx: RequestContext[str] = RequestContext("test-concurrent", default="prod")
    observed: dict[str, str] = {}

    async def run(label: str) -> None:
        token = ctx.set(label)
        await asyncio.sleep(0.01)  # yield control — a sibling task runs here
        observed[label] = ctx.get()
        ctx.reset(token)

    await asyncio.gather(run("shadow"), run("staging"))

    assert observed == {"shadow": "shadow", "staging": "staging"}
    assert ctx.get() == "prod"  # both tasks cleaned up after themselves
