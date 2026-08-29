"""Standalone worker script — no FastAPI, no HTTP layer anywhere in the call
path. The same kind of controller as fastapi_basic recovers via retry,
redirect, and queue steps, driven entirely by the bundled
validator_gateway.json, matched against exc.code exactly like a REST route
would use exc's status mapping.

Run it with:
    pip install -e .          # note: no [fastapi] extra needed
    python -m examples.worker_recovery.main
"""

import asyncio
from pathlib import Path
from typing import Any

from validator_gateway import (
    BaseController,
    PermissionDeniedError,
    RateLimitedError,
    UpstreamServiceError,
    ValidatorGateway,
)
from validator_gateway.recovery import JSONFilePolicyStore, QueuedJob, QueueSpec, RecoveryEngine

POLICY_PATH = Path(__file__).parent / "validator_gateway.json"


class FlakyUserController(BaseController):
    """Simulates a downstream dependency that fails a configurable number
    of times before succeeding (or never, if fail_times is large)."""

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times
        self.attempts = 0

    async def sync_user(self, user_id: str) -> dict[str, Any]:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise UpstreamServiceError(f"directory service unavailable (attempt {self.attempts})")
        return {"id": user_id, "synced": True}


class RateLimitedController(BaseController):
    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times
        self.attempts = 0

    async def sync_user(self, user_id: str) -> dict[str, Any]:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RateLimitedError(f"rate limited (attempt {self.attempts})")
        return {"id": user_id, "synced": True}


class BannedUserController(BaseController):
    async def sync_user(self, user_id: str) -> dict[str, Any]:
        raise PermissionDeniedError(f"not authorized to sync {user_id}")


async def degraded_sync(user_id: str) -> dict[str, Any]:
    return {"id": user_id, "synced": False, "degraded": True}


async def always_fails_fallback(user_id: str) -> dict[str, Any]:
    raise UpstreamServiceError("fallback is also down")


async def run_case(title: str, gateway: ValidatorGateway[Any], user_id: str) -> None:
    print(f"\n--- {title} ---")
    result = await gateway.handle(gateway.controller.sync_user, user_id)
    print(f"  result: {result}")


async def main() -> None:
    policy_store = JSONFilePolicyStore(POLICY_PATH)
    queued_jobs: list[QueuedJob] = []

    async def enqueue_hook(spec: QueueSpec, job: QueuedJob) -> None:
        queued_jobs.append(job)
        print(f"  -> queued to {spec.queue_name!r}: {job.model_dump()}")

    # Case 1: retry alone resolves it — fails twice, the "upstream_error"
    # policy's retry step allows up to 3 attempts.
    controller = FlakyUserController(fail_times=2)
    gateway = ValidatorGateway(
        controller, recovery=RecoveryEngine(policy_store=policy_store, enqueue_hook=enqueue_hook)
    )
    await run_case("RETRY recovers (2 transient failures, then succeeds)", gateway, "user-1")
    print(f"  controller.attempts = {controller.attempts}")

    # Case 2: retry exhausts, redirect resolves it.
    controller = FlakyUserController(fail_times=999)  # never succeeds on its own
    gateway = ValidatorGateway(
        controller, recovery=RecoveryEngine(policy_store=policy_store, enqueue_hook=enqueue_hook)
    )
    gateway.register_fallback("degraded_create_user", degraded_sync)
    await run_case("REDIRECT recovers (retries exhausted, fallback used)", gateway, "user-2")

    # Case 3: retry exhausts, redirect ALSO fails, falls through to queue.
    controller = FlakyUserController(fail_times=999)
    gateway = ValidatorGateway(
        controller, recovery=RecoveryEngine(policy_store=policy_store, enqueue_hook=enqueue_hook)
    )
    gateway.register_fallback("degraded_create_user", always_fails_fallback)
    await run_case("QUEUE handoff (retries and redirect both exhausted)", gateway, "user-3")

    # Case 4: a different code with its own retry policy (rate_limited).
    controller = RateLimitedController(fail_times=3)
    gateway = ValidatorGateway(
        controller, recovery=RecoveryEngine(policy_store=policy_store, enqueue_hook=enqueue_hook)
    )
    await run_case("rate_limited RETRY policy recovers", gateway, "user-4")

    # Case 5: FAIL step — non-retryable code, no recovery attempted at all.
    controller = BannedUserController()
    gateway = ValidatorGateway(
        controller, recovery=RecoveryEngine(policy_store=policy_store, enqueue_hook=enqueue_hook)
    )
    await run_case("permission_denied FAIL step (immediate formatted error)", gateway, "user-5")

    print(f"\nTotal jobs queued: {len(queued_jobs)}")


if __name__ == "__main__":
    asyncio.run(main())
