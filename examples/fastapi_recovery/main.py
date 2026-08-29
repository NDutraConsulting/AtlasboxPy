"""FastAPI + RecoveryEngine together: one route's gateway retries/redirects/
queues on failure, a second route wraps the exact same controller instance
with no recovery= attached at all — same controller, two gateways, per
Design Decision 8.

Run it with:
    pip install -e ".[fastapi]"
    uvicorn examples.fastapi_recovery.main:app --reload
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI

from validator_gateway import ValidatorGateway
from validator_gateway.fastapi_integration import to_json_response
from validator_gateway.recovery import JSONFilePolicyStore, QueuedJob, QueueSpec, RecoveryEngine

from .controllers import SyncController
from .services import SyncService

POLICY_PATH = Path(__file__).parent / "validator_gateway.json"

service = SyncService()
controller = SyncController(service)

queued_jobs: list[QueuedJob] = []


async def enqueue_hook(spec: QueueSpec, job: QueuedJob) -> None:
    queued_jobs.append(job)


async def degraded_sync(user_id: str) -> dict[str, Any]:
    return {"id": user_id, "synced": False, "degraded": True}


recovery_engine = RecoveryEngine(
    policy_store=JSONFilePolicyStore(POLICY_PATH), enqueue_hook=enqueue_hook
)
recovery_gateway = ValidatorGateway(controller, recovery=recovery_engine)
recovery_gateway.register_fallback("degraded_sync", degraded_sync)

# Same controller instance, deliberately built WITHOUT recovery= — the
# fail-fast comparison this example exists to demonstrate.
strict_gateway = ValidatorGateway(controller)

app = FastAPI(title="validator_gateway — recovery example")
router = APIRouter()


@router.post("/sync/{user_id}")
async def sync_user(user_id: str):
    result = await recovery_gateway.handle(recovery_gateway.controller.sync_user, user_id)
    return to_json_response(result)


@router.post("/sync-strict/{user_id}")
async def sync_user_strict(user_id: str):
    result = await strict_gateway.handle(strict_gateway.controller.sync_user, user_id)
    return to_json_response(result)


app.include_router(router)
