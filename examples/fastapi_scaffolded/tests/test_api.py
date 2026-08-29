"""P12-T2: proves the CLI's scaffold output is usable, not just importable
— these tests run against the actual generated controllers/example_controller.py
and validator_gateways/example_gateway.py, unmodified since `validator-gateway
init` produced them."""

from fastapi.testclient import TestClient
from main import app  # resolvable via conftest.py's sys.path insertion


def test_success_path_from_generated_controller():
    client = TestClient(app)
    resp = client.get("/examples/1")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"id": "1", "name": "Example"}


def test_not_found_from_generated_controller():
    client = TestClient(app)
    resp = client.get("/examples/2")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
