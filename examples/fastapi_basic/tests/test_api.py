"""P9-T1/P12-T1: end-to-end tests against the fastapi_basic example itself
(not a synthetic test app), via a real fastapi.testclient.TestClient."""

from fastapi.testclient import TestClient

from examples.fastapi_basic.main import app


def test_full_crud_lifecycle():
    client = TestClient(app)

    created = client.post("/users", json={"name": "Ada", "email": "ada@example.com"})
    assert created.status_code == 200
    user_id = created.json()["data"]["id"]

    fetched = client.get(f"/users/{user_id}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["name"] == "Ada"

    listed = client.get("/users")
    assert listed.status_code == 200
    assert any(u["id"] == user_id for u in listed.json()["data"])

    patched = client.patch(f"/users/{user_id}", json={"name": "Ada Lovelace"})
    assert patched.status_code == 200
    assert patched.json()["data"]["name"] == "Ada Lovelace"
    assert patched.json()["data"]["email"] == "ada@example.com"  # untouched by the patch

    deleted = client.delete(f"/users/{user_id}")
    assert deleted.status_code == 200

    gone = client.get(f"/users/{user_id}")
    assert gone.status_code == 404


def test_not_found_maps_to_404():
    client = TestClient(app)
    resp = client.get("/users/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_duplicate_email_maps_to_409():
    client = TestClient(app)
    client.post("/users", json={"name": "Grace", "email": "grace@example.com"})
    resp = client.post("/users", json={"name": "Grace 2", "email": "grace@example.com"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already_exists"


def test_thin_registry_driven_route_works_and_is_documented_in_openapi():
    client = TestClient(app)

    resp = client.post("/users/thin", json={"name": "Linus", "email": "linus@example.com"})
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Linus"

    schema = client.get("/openapi.json").json()
    thin_op = schema["paths"]["/users/thin"]["post"]
    assert "requestBody" in thin_op
    assert "409" in thin_op["responses"]
