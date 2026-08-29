"""API-level tests for the Kanban demo. The static frontend (HTML/CSS/JS)
is exercised manually via a browser and via a live uvicorn + curl pass —
pytest here covers the validator_gateway-backed REST API and static-file
serving, not DOM behavior."""

from datetime import datetime

from fastapi.testclient import TestClient

from examples.fastapi_kanban.logging_setup import _LOG_DIR
from examples.fastapi_kanban.main import app


def _create_board(client: TestClient, name: str = "Launch plan") -> dict:
    resp = client.post("/api/boards", json={"name": name})
    assert resp.status_code == 200
    return resp.json()["data"]


def test_create_board_gets_three_default_columns():
    client = TestClient(app)
    board = _create_board(client)
    assert len(board["columns"]) == 3
    assert [c["name"] for c in board["columns"]] == ["To Do", "In Progress", "Done"]


def test_create_board_rejects_empty_name():
    client = TestClient(app)
    resp = client.post("/api/boards", json={"name": "   "})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"


def test_list_boards_reflects_column_and_card_counts():
    client = TestClient(app)
    board = _create_board(client)
    column_id = board["columns"][0]["id"]
    client.post(f"/api/boards/{board['id']}/cards", json={"column_id": column_id, "title": "Task 1"})

    resp = client.get("/api/boards")
    assert resp.status_code == 200
    summary = next(b for b in resp.json()["data"] if b["id"] == board["id"])
    assert summary["column_count"] == 3
    assert summary["card_count"] == 1


def test_get_missing_board_returns_404():
    client = TestClient(app)
    resp = client.get("/api/boards/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_add_column_and_reject_duplicate_name():
    client = TestClient(app)
    board = _create_board(client)

    resp = client.post(f"/api/boards/{board['id']}/columns", json={"name": "Blocked"})
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Blocked"

    dup = client.post(f"/api/boards/{board['id']}/columns", json={"name": "Blocked"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"


def test_delete_column_with_cards_conflicts():
    client = TestClient(app)
    board = _create_board(client)
    column_id = board["columns"][0]["id"]
    client.post(f"/api/boards/{board['id']}/cards", json={"column_id": column_id, "title": "Task"})

    resp = client.delete(f"/api/boards/{board['id']}/columns/{column_id}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_delete_empty_column_succeeds():
    client = TestClient(app)
    board = _create_board(client)
    column_id = board["columns"][-1]["id"]  # "Done" — created empty

    resp = client.delete(f"/api/boards/{board['id']}/columns/{column_id}")
    assert resp.status_code == 200

    refreshed = client.get(f"/api/boards/{board['id']}").json()["data"]
    assert column_id not in [c["id"] for c in refreshed["columns"]]


def test_full_card_lifecycle_create_update_move_delete():
    client = TestClient(app)
    board = _create_board(client)
    todo_id = board["columns"][0]["id"]
    doing_id = board["columns"][1]["id"]

    created = client.post(
        f"/api/boards/{board['id']}/cards",
        json={"column_id": todo_id, "title": "Write docs", "description": "Draft v1"},
    )
    assert created.status_code == 200
    card = created.json()["data"]
    assert card["column_id"] == todo_id

    updated = client.patch(f"/api/cards/{card['id']}", json={"title": "Doc final"})
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "Doc final"
    assert updated.json()["data"]["description"] == "Draft v1"  # untouched

    moved = client.post(f"/api/cards/{card['id']}/move", json={"column_id": doing_id})
    assert moved.status_code == 200
    assert moved.json()["data"]["column_id"] == doing_id

    deleted = client.delete(f"/api/cards/{card['id']}")
    assert deleted.status_code == 200

    missing = client.patch(f"/api/cards/{card['id']}", json={"title": "x"})
    assert missing.status_code == 404


def test_create_card_rejects_empty_title():
    client = TestClient(app)
    board = _create_board(client)
    column_id = board["columns"][0]["id"]
    resp = client.post(
        f"/api/boards/{board['id']}/cards", json={"column_id": column_id, "title": "  "}
    )
    assert resp.status_code == 422


def test_delete_board_removes_it():
    client = TestClient(app)
    board = _create_board(client)
    resp = client.delete(f"/api/boards/{board['id']}")
    assert resp.status_code == 200
    assert client.get(f"/api/boards/{board['id']}").status_code == 404


def test_static_index_page_is_served():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Kanban Boards" in resp.text


def test_static_feature_assets_are_served():
    client = TestClient(app)
    js = client.get("/features/board/board-controller.js")
    assert js.status_code == 200
    css = client.get("/features/boards/boards.css")
    assert css.status_code == 200


def test_gateway_traffic_is_logged_success_and_error():
    """Every call through a gateway — not just failures — lands in
    logs/{today}_validator_gateway.log (see logging_setup.handle_and_log),
    carrying the actual request payload and the actual JSON response
    envelope handed back to the api_router. Lines are tagged with the
    gateway's own source_info (e.g. "board_validator_gateway.py"), not the
    controller's class name."""
    client = TestClient(app)
    board = _create_board(client, name="Logged board")
    client.get("/api/boards/does-not-exist")  # a failing call, on purpose

    log_path = _LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_validator_gateway.log"
    assert log_path.exists()
    lines = log_path.read_text().splitlines()

    # The log file persists across the whole test session (other tests also
    # create boards), so match on this test's own data, not just the method.
    create_line = next(line for line in lines if "Logged board" in line)
    assert "boards_validator_gateway.py.create_board" in create_line
    assert 'request=[{"name": "Logged board"}]' in create_line
    assert '"status": "success"' in create_line
    assert board["id"] in create_line  # the created board's id is in the logged response

    not_found_line = next(line for line in lines if "board_validator_gateway.py.get_board" in line)
    assert 'request=["does-not-exist"]' in not_found_line
    assert '"status": "error"' in not_found_line
    assert '"code": "not_found"' in not_found_line


def test_card_title_over_ten_characters_is_rejected():
    client = TestClient(app)
    board = _create_board(client)
    column_id = board["columns"][0]["id"]

    resp = client.post(
        f"/api/boards/{board['id']}/cards",
        json={"column_id": column_id, "title": "12345678901"},  # 11 chars
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"
    assert "10 characters" in resp.json()["error"]["message"]


def test_card_title_at_exactly_ten_characters_is_allowed():
    client = TestClient(app)
    board = _create_board(client)
    column_id = board["columns"][0]["id"]

    resp = client.post(
        f"/api/boards/{board['id']}/cards",
        json={"column_id": column_id, "title": "1234567890"},  # exactly 10
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "1234567890"


def test_updating_a_card_title_past_ten_characters_is_rejected():
    client = TestClient(app)
    board = _create_board(client)
    column_id = board["columns"][0]["id"]
    card = client.post(
        f"/api/boards/{board['id']}/cards", json={"column_id": column_id, "title": "short"}
    ).json()["data"]

    resp = client.patch(f"/api/cards/{card['id']}", json={"title": "way too long"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"


def test_simulate_db_error_toggle_causes_upstream_error_then_recovers():
    client = TestClient(app)
    try:
        toggled_on = client.post("/api/debug/db-connection", json={"enabled": True})
        assert toggled_on.status_code == 200
        assert toggled_on.json() == {"simulate_db_error": True}

        while_down = client.post("/api/boards", json={"name": "Should fail"})
        assert while_down.status_code == 502
        assert while_down.json()["error"]["code"] == "upstream_error"

        # Reads are affected too, not just writes.
        list_while_down = client.get("/api/boards")
        assert list_while_down.status_code == 502
    finally:
        client.post("/api/debug/db-connection", json={"enabled": False})

    recovered = client.post("/api/boards", json={"name": "Back online"})
    assert recovered.status_code == 200
