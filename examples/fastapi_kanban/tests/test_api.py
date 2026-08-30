"""API-level tests for the Kanban demo. The static frontend (HTML/CSS/JS)
is exercised manually via a browser and via a live uvicorn + curl pass —
pytest here covers the Starlette + SQLite-backed REST API, not DOM
behavior.

Each test gets its own fresh in-memory SQLite database via the `client`
fixture — full isolation, no state bleeding between tests (unlike the
shared traffic log file, which persists across the whole test session and
is handled separately, by matching on each test's own unique data)."""

from datetime import datetime

import pytest
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from examples.fastapi_kanban.db import init_db, make_engine, make_session_factory
from examples.fastapi_kanban.logging_setup import _LOG_DIR
from examples.fastapi_kanban.main import create_app
from examples.fastapi_kanban.services.db_simulation import set_simulation


@pytest.fixture
async def client():
    engine = make_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    await init_db(engine)
    app = create_app(session_factory=make_session_factory(engine))
    set_simulation(None)
    with TestClient(app) as test_client:
        yield test_client
    set_simulation(None)
    await engine.dispose()


def _create_board(client: TestClient, name: str = "Launch plan") -> dict:
    resp = client.post("/api/boards", json={"name": name})
    assert resp.status_code == 200
    return resp.json()["data"]


def test_create_board_gets_three_default_columns(client):
    board = _create_board(client)
    assert len(board["columns"]) == 3
    assert [c["name"] for c in board["columns"]] == ["To Do", "In Progress", "Done"]


def test_create_board_rejects_empty_name(client):
    resp = client.post("/api/boards", json={"name": "   "})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"


def test_list_boards_reflects_column_and_card_counts(client):
    board = _create_board(client)
    column_id = board["columns"][0]["id"]
    client.post(f"/api/boards/{board['id']}/cards", json={"column_id": column_id, "title": "Task 1"})

    resp = client.get("/api/boards")
    assert resp.status_code == 200
    summary = next(b for b in resp.json()["data"] if b["id"] == board["id"])
    assert summary["column_count"] == 3
    assert summary["card_count"] == 1


def test_get_missing_board_returns_404(client):
    resp = client.get("/api/boards/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_add_column_and_reject_duplicate_name(client):
    board = _create_board(client)

    resp = client.post(f"/api/boards/{board['id']}/columns", json={"name": "Blocked"})
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Blocked"

    dup = client.post(f"/api/boards/{board['id']}/columns", json={"name": "Blocked"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"


def test_delete_column_with_cards_conflicts(client):
    board = _create_board(client)
    column_id = board["columns"][0]["id"]
    client.post(f"/api/boards/{board['id']}/cards", json={"column_id": column_id, "title": "Task"})

    resp = client.delete(f"/api/boards/{board['id']}/columns/{column_id}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_delete_empty_column_succeeds(client):
    board = _create_board(client)
    column_id = board["columns"][-1]["id"]  # "Done" — created empty

    resp = client.delete(f"/api/boards/{board['id']}/columns/{column_id}")
    assert resp.status_code == 200

    refreshed = client.get(f"/api/boards/{board['id']}").json()["data"]
    assert column_id not in [c["id"] for c in refreshed["columns"]]


def test_full_card_lifecycle_create_update_move_delete(client):
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
    assert card["board_id"] == board["id"]

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


def test_move_card_to_column_on_a_different_board_is_rejected(client):
    """CardService trusts the column_id it's given; the controller is the
    one that validates it belongs to the card's own board, via
    BoardService.column_exists() — this proves that cross-entity check
    actually runs."""
    board_a = _create_board(client, name="Board A")
    board_b = _create_board(client, name="Board B")
    card = client.post(
        f"/api/boards/{board_a['id']}/cards",
        json={"column_id": board_a["columns"][0]["id"], "title": "x"},
    ).json()["data"]

    resp = client.post(
        f"/api/cards/{card['id']}/move", json={"column_id": board_b["columns"][0]["id"]}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_create_card_rejects_empty_title(client):
    board = _create_board(client)
    column_id = board["columns"][0]["id"]
    resp = client.post(
        f"/api/boards/{board['id']}/cards", json={"column_id": column_id, "title": "  "}
    )
    assert resp.status_code == 422


def test_create_card_on_unknown_column_is_not_found(client):
    board = _create_board(client)
    resp = client.post(
        f"/api/boards/{board['id']}/cards", json={"column_id": "nope", "title": "x"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_delete_board_removes_it(client):
    board = _create_board(client)
    resp = client.delete(f"/api/boards/{board['id']}")
    assert resp.status_code == 200
    assert client.get(f"/api/boards/{board['id']}").status_code == 404


def test_static_index_page_is_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Kanban Boards" in resp.text


def test_static_feature_assets_are_served(client):
    js = client.get("/features/board/board-controller.js")
    assert js.status_code == 200
    css = client.get("/features/boards/boards.css")
    assert css.status_code == 200


def test_gateway_traffic_is_logged_with_source_json_method_and_case(client):
    """Every call through the gateway — not just failures — lands in
    logs/{today}_validator_gateway.log, tagged with the gateway's required
    source_json (real request url/method/caller_type — not a static
    string), the controller method called, the classified FailureCase (or
    "success"), and the actual request/response JSON."""
    board = _create_board(client, name="Logged board")
    client.get("/api/boards/does-not-exist")  # a failing call, on purpose

    log_path = _LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_validator_gateway.log"
    assert log_path.exists()
    lines = log_path.read_text().splitlines()

    # The log file persists across every test run, not just this session
    # (a prior run may have created its own "Logged board" with a
    # different id) — match on this run's own unique board id, searching
    # from the most recent lines, so a stale entry can never be picked up.
    create_line = next(line for line in reversed(lines) if board["id"] in line)
    assert '"url": "/api/boards"' in create_line
    assert '"method": "POST"' in create_line
    assert '"caller_type": "api_route"' in create_line
    assert "method=create_board" in create_line
    assert "case=success" in create_line
    assert 'request=[{"name": "Logged board"}]' in create_line
    assert '"status": "success"' in create_line

    not_found_line = next(line for line in reversed(lines) if "does-not-exist" in line)
    assert '"url": "/api/boards/does-not-exist"' in not_found_line
    assert '"method": "GET"' in not_found_line
    assert "method=get_board" in not_found_line
    assert "case=not_found" in not_found_line  # the classified FailureCase, not just "error"
    assert '"status": "error"' in not_found_line
    assert '"code": "not_found"' in not_found_line


def test_card_title_over_ten_characters_is_rejected(client):
    board = _create_board(client)
    column_id = board["columns"][0]["id"]

    resp = client.post(
        f"/api/boards/{board['id']}/cards",
        json={"column_id": column_id, "title": "12345678901"},  # 11 chars
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"
    assert "10 characters" in resp.json()["error"]["message"]


def test_card_title_at_exactly_ten_characters_is_allowed(client):
    board = _create_board(client)
    column_id = board["columns"][0]["id"]

    resp = client.post(
        f"/api/boards/{board['id']}/cards",
        json={"column_id": column_id, "title": "1234567890"},  # exactly 10
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "1234567890"


def test_updating_a_card_title_past_ten_characters_is_rejected(client):
    board = _create_board(client)
    column_id = board["columns"][0]["id"]
    card = client.post(
        f"/api/boards/{board['id']}/cards", json={"column_id": column_id, "title": "short"}
    ).json()["data"]

    resp = client.patch(f"/api/cards/{card['id']}", json={"title": "way too long"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_failed"


def test_simulate_db_error_toggle_causes_upstream_error_then_recovers(client):
    toggled_on = client.post("/api/debug/db-connection", json={"enabled": True, "mode": "error"})
    assert toggled_on.status_code == 200
    assert toggled_on.json() == {"simulate_db_error": True, "mode": "error"}

    while_down = client.post("/api/boards", json={"name": "Should fail"})
    assert while_down.status_code == 502
    assert while_down.json()["error"]["code"] == "upstream_error"

    # Reads are affected too, not just writes.
    list_while_down = client.get("/api/boards")
    assert list_while_down.status_code == 502

    client.post("/api/debug/db-connection", json={"enabled": False})
    recovered = client.post("/api/boards", json={"name": "Back online"})
    assert recovered.status_code == 200


def test_simulate_db_timeout_also_maps_to_upstream_error(client):
    client.post("/api/debug/db-connection", json={"enabled": True, "mode": "timeout"})
    resp = client.post("/api/boards", json={"name": "x"})
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"
    client.post("/api/debug/db-connection", json={"enabled": False})


def test_get_board_redirects_to_degraded_gateway_when_db_is_down(client):
    """KanbanValidatorGateway's UPSTREAM_UNAVAILABLE case redirects a failed
    get_board read to DegradedBoardValidatorGateway — a real, different
    ValidatorGateway — instead of just reporting the outage. Writes get no
    such treatment: there's nothing sensible to "degrade" a write to."""
    board = _create_board(client, name="Degrade me")

    client.post("/api/debug/db-connection", json={"enabled": True})

    degraded = client.get(f"/api/boards/{board['id']}")
    assert degraded.status_code == 200  # NOT 502 — the redirect absorbed the failure
    data = degraded.json()["data"]
    assert data["id"] == board["id"]
    assert data["degraded"] is True
    assert data["columns"] == []

    # A write to the same board still just reports the outage.
    write_while_down = client.delete(f"/api/boards/{board['id']}")
    assert write_while_down.status_code == 502
    assert write_while_down.json()["error"]["code"] == "upstream_error"

    client.post("/api/debug/db-connection", json={"enabled": False})


def test_card_validation_failure_includes_scenario_specific_hint(client):
    """The VALIDATION_FAILED case's custom messaging (defined in
    kanban_validator_gateway.py's match/case) augments the raw exception
    message rather than just passing it through verbatim."""
    board = _create_board(client)
    column_id = board["columns"][0]["id"]

    resp = client.post(
        f"/api/boards/{board['id']}/cards",
        json={"column_id": column_id, "title": "way too long a title"},
    )
    message = resp.json()["error"]["message"]
    assert message.startswith("Card title must be at most 10 characters")  # the raw exc.message
    assert "hint: card titles are capped at 10 characters in this demo" in message  # the addition


def test_board_name_validation_failure_includes_scenario_specific_hint(client):
    """Same VALIDATION_FAILED case, disambiguated by message content since
    board-name and card-title validation share the same DomainError code."""
    resp = client.post("/api/boards", json={"name": "   "})
    message = resp.json()["error"]["message"]
    assert message.startswith("Board name must not be empty")  # the raw exc.message
    assert "hint: every board starts with 3 default columns" in message  # the addition
