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
from examples.fastapi_kanban.db_simulation import set_simulation


@pytest.fixture
async def client():
    engine = make_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    await init_db(engine)
    app = create_app(session_factory=make_session_factory(engine))
    await set_simulation(None)
    with TestClient(app) as test_client:
        yield test_client
    await set_simulation(None)
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


def test_traffic_is_logged_with_source_method_and_status(client):
    """Every call through a controller — not just failures — lands in
    logs/{today}_atlasboxpy_controller.log, tagged with the real request
    url/method/caller_type, the controller method called, the outcome
    ("success" or the DomainError's own code), and the actual
    request/response JSON. Wired via main.py's `_call()` helper, the one
    place every route funnels through on its way to a controller."""
    board = _create_board(client, name="Logged board")
    client.get("/api/boards/does-not-exist")  # a failing call, on purpose

    log_path = _LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_atlasboxpy_controller.log"
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
    assert "status=success" in create_line
    assert 'request=[{"name": "Logged board"}]' in create_line
    assert '"status": "success"' in create_line

    not_found_line = next(line for line in reversed(lines) if "does-not-exist" in line)
    assert '"url": "/api/boards/does-not-exist"' in not_found_line
    assert '"method": "GET"' in not_found_line
    assert "method=get_board" in not_found_line
    assert "status=not_found" in not_found_line  # the DomainError's own code, not just "error"
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


def test_writes_invalidate_the_cached_board(client):
    """A write affecting a board (adding a column here) invalidates that
    board's cache entry in KanbanRepository, so the next read reflects the
    change instead of serving stale cached data."""
    board = _create_board(client, name="Invalidate me")
    assert len(client.get(f"/api/boards/{board['id']}").json()["data"]["columns"]) == 3

    client.post(f"/api/boards/{board['id']}/columns", json={"name": "Backlog"})

    refreshed = client.get(f"/api/boards/{board['id']}").json()["data"]
    assert len(refreshed["columns"]) == 4
    assert any(c["name"] == "Backlog" for c in refreshed["columns"])


def test_cached_board_survives_db_being_down(client):
    """KanbanRepository caches get_board — a board that's already been read
    (creating one populates the cache via create_board()'s own trailing
    get_board() call) keeps serving correctly even while the (simulated)
    database is down, since the read never has to reach it. This is the
    payoff of caching in the repository, not just a memory-saving trick."""
    board = _create_board(client, name="Cached board")

    client.post("/api/debug/db-connection", json={"enabled": True})

    still_fine = client.get(f"/api/boards/{board['id']}")
    assert still_fine.status_code == 200
    data = still_fine.json()["data"]
    assert data["name"] == "Cached board"
    assert "degraded" not in data  # served from cache, never touched the "down" database

    client.post("/api/debug/db-connection", json={"enabled": False})


async def test_get_board_redirects_to_degraded_gateway_when_db_is_down():
    """KanbanController.get_board() catches its own UpstreamServiceError and
    returns a degraded, clearly-marked payload instead of reporting the
    outage — but only for a genuine cache miss. This test uses a second app
    instance sharing the same database but with its own, empty repository
    cache (standing in for "just after a restart"), so the read has nowhere
    to go but the (simulated) broken database — the scenario the previous,
    single-app version of this test stopped exercising once get_board()
    started caching (see test_cached_board_survives_db_being_down above).
    Writes get no degraded treatment: there's nothing sensible to "degrade"
    a write to."""
    engine = make_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    await init_db(engine)
    session_factory = make_session_factory(engine)
    await set_simulation(None)

    with TestClient(create_app(session_factory=session_factory)) as writer:
        board = _create_board(writer, name="Degrade me")

        writer.post("/api/debug/db-connection", json={"enabled": True})

        with TestClient(create_app(session_factory=session_factory)) as reader:
            degraded = reader.get(f"/api/boards/{board['id']}")
            assert degraded.status_code == 200  # NOT 502 — the fallback absorbed the failure
            data = degraded.json()["data"]
            assert data["id"] == board["id"]
            assert data["degraded"] is True
            assert data["columns"] == []

        # A write to the same board still just reports the outage.
        write_while_down = writer.delete(f"/api/boards/{board['id']}")
        assert write_while_down.status_code == 502
        assert write_while_down.json()["error"]["code"] == "upstream_error"

        writer.post("/api/debug/db-connection", json={"enabled": False})

    await set_simulation(None)
    await engine.dispose()


def test_card_validation_failure_includes_scenario_specific_hint(client):
    """KanbanController.create_card()/update_card() catch their own
    ValidationFailedError and append a scenario-specific hint rather than
    passing the raw exception message through verbatim."""
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
    """Same DomainError code (validation_failed) as the card-title case
    above, but the hint is chosen by KanbanController.create_board() itself
    — no message-sniffing needed, since each method already knows what it
    can fail at."""
    resp = client.post("/api/boards", json={"name": "   "})
    message = resp.json()["error"]["message"]
    assert message.startswith("Board name must not be empty")  # the raw exc.message
    assert "hint: every board starts with 3 default columns" in message  # the addition
