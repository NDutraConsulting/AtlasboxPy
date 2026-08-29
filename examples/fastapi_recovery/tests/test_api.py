"""P12-T3: FastAPI + RecoveryEngine over real HTTP, plus the same-controller
fail-fast comparison from Design Decision 8."""

from fastapi.testclient import TestClient

from examples.fastapi_recovery.main import app, queued_jobs


def test_retry_recovers_and_client_still_gets_200():
    client = TestClient(app)
    resp = client.post("/sync/flaky-http-1")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"id": "flaky-http-1", "synced": True}


def test_retry_exhausted_then_redirect_recovers():
    client = TestClient(app)
    resp = client.post("/sync/always-fails-http-1")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"id": "always-fails-http-1", "synced": False, "degraded": True}


def test_queued_failure_returns_distinct_accepted_shape_not_a_hang():
    client = TestClient(app)
    before = len(queued_jobs)

    resp = client.post("/sync/quota-http-1")

    assert resp.status_code == 200
    assert resp.json()["data"] is None  # "accepted for later processing", not a real result
    assert len(queued_jobs) == before + 1
    assert queued_jobs[-1].original_code == "rate_limited"


def test_same_controller_strict_gateway_surfaces_raw_error_instead():
    client = TestClient(app)
    resp = client.post("/sync-strict/always-fails-http-2")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"
