import json

import pytest

from validator_gateway.controller import BaseController
from validator_gateway.exceptions import UpstreamServiceError
from validator_gateway.gateway import UnregisteredFallbackError, ValidatorGateway
from validator_gateway.recovery import (
    JSONFilePolicyStore,
    PolicyValidationError,
    QueuedJob,
    QueueSpec,
    RecoveryAction,
    RecoveryEngine,
    RecoveryStep,
    RedirectSpec,
    RetrySpec,
)

EXAMPLE_POLICY = {
    "upstream_error": [
        {"action": "retry", "retry": {"max_attempts": 3, "backoff_base_seconds": 0.001}},
        {"action": "redirect", "redirect": {"target": "degraded_create_user"}},
        {"action": "queue", "queue": {"queue_name": "recovery.upstream_error"}},
    ],
    "rate_limited": [
        {
            "action": "retry",
            "retry": {"max_attempts": 5, "backoff_base_seconds": 0.001, "backoff_multiplier": 2.0},
        }
    ],
    "permission_denied": [{"action": "fail"}],
}


class FlakyController(BaseController):
    def __init__(self, fail_times: int = 0):
        super().__init__()
        self.fail_times = fail_times
        self.calls = 0

    async def do_work(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise UpstreamServiceError("upstream flaked")
        return {"ok": True}


class AlwaysFailsController(BaseController):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def do_work(self, *args, **kwargs):
        self.calls += 1
        raise UpstreamServiceError("upstream always fails")


# --- P5-T1: recovery data model ---


def test_models_round_trip_through_json():
    step = RecoveryStep(
        action=RecoveryAction.RETRY,
        retry=RetrySpec(max_attempts=5),
    )
    restored = RecoveryStep.model_validate_json(step.model_dump_json())
    assert restored == step

    job = QueuedJob(
        controller_class="UserController",
        method_name="get_user",
        args=["123"],
        kwargs={},
        original_code="upstream_error",
        attempt_count=1,
    )
    assert QueuedJob.model_validate_json(job.model_dump_json()) == job


def test_redirect_and_queue_spec_round_trip():
    redirect = RedirectSpec(target="fallback")
    assert RedirectSpec.model_validate_json(redirect.model_dump_json()) == redirect

    queue = QueueSpec(queue_name="q", max_delay_seconds=30)
    assert QueueSpec.model_validate_json(queue.model_dump_json()) == queue


# --- P5-T2: PolicyStore / JSONFilePolicyStore ---


def test_json_file_policy_store_loads_example_shape(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(json.dumps(EXAMPLE_POLICY))
    store = JSONFilePolicyStore(path)
    steps = store.get_policy("upstream_error")
    assert len(steps) == 3
    assert steps[0].action == RecoveryAction.RETRY
    assert steps[1].action == RecoveryAction.REDIRECT
    assert steps[2].action == RecoveryAction.QUEUE


def test_json_file_policy_store_unknown_code_raises(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(json.dumps({"not_a_real_code": [{"action": "fail"}]}))
    with pytest.raises(PolicyValidationError, match="not_a_real_code"):
        JSONFilePolicyStore(path)


def test_json_file_policy_store_rejects_retry_on_nonretryable_code(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(json.dumps({"permission_denied": [{"action": "retry"}]}))
    with pytest.raises(PolicyValidationError, match="permission_denied"):
        JSONFilePolicyStore(path)


def test_json_file_policy_store_missing_code_returns_empty(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(json.dumps(EXAMPLE_POLICY))
    store = JSONFilePolicyStore(path)
    assert store.get_policy("not_found") == []


# --- P5-T4: redirect target allowlist ---


@pytest.mark.asyncio
async def test_register_and_resolve_fallback():
    controller = FlakyController()
    gateway = ValidatorGateway(controller)

    async def fallback():
        return {"degraded": True}

    gateway.register_fallback("degraded_create_user", fallback)
    resolved = gateway.resolve_fallback("degraded_create_user")
    assert await resolved() == {"degraded": True}


def test_resolve_unregistered_fallback_raises():
    controller = FlakyController()
    gateway = ValidatorGateway(controller)
    with pytest.raises(UnregisteredFallbackError, match="never_registered"):
        gateway.resolve_fallback("never_registered")


# --- P5-T5: RecoveryEngine match/case dispatch ---


@pytest.mark.asyncio
async def test_retry_then_redirect_chain_returns_redirect_result(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(json.dumps(EXAMPLE_POLICY))
    engine = RecoveryEngine(policy_store=JSONFilePolicyStore(path))

    controller = AlwaysFailsController()
    gateway = ValidatorGateway(controller, recovery=engine)

    async def fallback():
        return {"degraded": True}

    gateway.register_fallback("degraded_create_user", fallback)

    resp = await gateway.handle(gateway.controller.do_work)
    assert resp.status == "success"
    assert resp.data == {"degraded": True}
    # 1 initial call (inside handle()) + 3 retry-step attempts, all failing, before redirect
    assert controller.calls == 4


@pytest.mark.asyncio
async def test_no_fail_step_reraises_original_exception(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(
        json.dumps(
            {
                "upstream_error": [
                    {"action": "retry", "retry": {"max_attempts": 1, "backoff_base_seconds": 0}}
                ]
            }
        )
    )
    engine = RecoveryEngine(policy_store=JSONFilePolicyStore(path))
    controller = AlwaysFailsController()
    gateway = ValidatorGateway(controller, recovery=engine)

    resp = await gateway.handle(gateway.controller.do_work)
    assert resp.status == "error"
    assert resp.error.code == "upstream_error"


@pytest.mark.asyncio
async def test_max_total_steps_guard_terminates_pathological_policy(tmp_path):
    steps = [{"action": "retry", "retry": {"max_attempts": 1, "backoff_base_seconds": 0}}] * 15
    path = tmp_path / "validator_gateway.json"
    path.write_text(json.dumps({"upstream_error": steps}))
    engine = RecoveryEngine(policy_store=JSONFilePolicyStore(path), max_total_steps=3)
    controller = AlwaysFailsController()
    gateway = ValidatorGateway(controller, recovery=engine)

    resp = await gateway.handle(gateway.controller.do_work)
    assert resp.status == "error"
    # 1 initial call + 3 allowed steps (one call each, max_attempts=1), then the guard trips
    assert controller.calls == 4


# --- P5-T6: EnqueueHook ---


@pytest.mark.asyncio
async def test_queue_step_invokes_enqueue_hook_with_populated_job(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(
        json.dumps(
            {
                "upstream_error": [
                    {"action": "retry", "retry": {"max_attempts": 1, "backoff_base_seconds": 0}},
                    {"action": "queue", "queue": {"queue_name": "recovery.upstream_error"}},
                ]
            }
        )
    )

    enqueued: list[tuple[QueueSpec, QueuedJob]] = []

    async def enqueue_hook(spec: QueueSpec, job: QueuedJob) -> None:
        enqueued.append((spec, job))

    engine = RecoveryEngine(policy_store=JSONFilePolicyStore(path), enqueue_hook=enqueue_hook)
    controller = AlwaysFailsController()
    gateway = ValidatorGateway(controller, recovery=engine)

    resp = await gateway.handle(gateway.controller.do_work, "arg1", kw="v")
    assert resp.status == "success"
    assert resp.data is None
    assert len(enqueued) == 1
    spec, job = enqueued[0]
    assert spec.queue_name == "recovery.upstream_error"
    assert job.controller_class == "AlwaysFailsController"
    assert job.method_name == "do_work"
    assert job.args == ["arg1"]
    assert job.kwargs == {"kw": "v"}
    assert job.original_code == "upstream_error"
    json.dumps(job.model_dump())  # args/kwargs are JSON-serializable


# --- P5-T7: wiring into handle() ---


@pytest.mark.asyncio
async def test_gateway_without_recovery_fails_fast_with_zero_retries():
    controller = AlwaysFailsController()
    gateway = ValidatorGateway(controller)
    resp = await gateway.handle(gateway.controller.do_work)
    assert resp.status == "error"
    assert controller.calls == 1


@pytest.mark.asyncio
async def test_gateway_with_recovery_succeeds_after_transient_failures(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(
        json.dumps(
            {
                "upstream_error": [
                    {"action": "retry", "retry": {"max_attempts": 3, "backoff_base_seconds": 0.001}}
                ]
            }
        )
    )
    engine = RecoveryEngine(policy_store=JSONFilePolicyStore(path))
    controller = FlakyController(fail_times=2)
    gateway = ValidatorGateway(controller, recovery=engine)

    resp = await gateway.handle(gateway.controller.do_work)
    assert resp.status == "success"
    assert resp.data == {"ok": True}
    assert controller.calls == 3


@pytest.mark.asyncio
async def test_same_controller_rest_vs_worker_gateway_call_counts(tmp_path):
    path = tmp_path / "validator_gateway.json"
    path.write_text(
        json.dumps(
            {
                "upstream_error": [
                    {"action": "retry", "retry": {"max_attempts": 3, "backoff_base_seconds": 0.001}}
                ]
            }
        )
    )
    rest_controller = AlwaysFailsController()
    rest_gateway = ValidatorGateway(rest_controller)
    await rest_gateway.handle(rest_gateway.controller.do_work)
    assert rest_controller.calls == 1

    worker_controller = AlwaysFailsController()
    worker_gateway = ValidatorGateway(
        worker_controller, recovery=RecoveryEngine(policy_store=JSONFilePolicyStore(path))
    )
    await worker_gateway.handle(worker_gateway.controller.do_work)
    # 1 initial call + 3 retry-step attempts, all against the same failing controller
    assert worker_controller.calls == 4
