"""API-level tests for the Kanban demo. The static frontend (HTML/CSS/JS)
is exercised manually via a browser and via a live uvicorn + curl pass —
pytest here covers the Starlette + SQLite-backed REST API, not DOM
behavior.

Each test gets its own fresh in-memory SQLite database via the `client`
fixture — full isolation, no state bleeding between tests (unlike the
shared traffic log file, which persists across the whole test session and
is handled separately, by matching on each test's own unique data)."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from atlasboxpy_db import StorageUnavailable
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from examples.fastapi_agile_project_planner.app.backend.infrastructure.database.db_connections.db_simulation import (
    set_simulation,
)
from examples.fastapi_agile_project_planner.app.backend.infrastructure.database.session import (
    init_db,
    make_engine,
    make_session_factory,
)
from examples.fastapi_agile_project_planner.app.backend.infrastructure.repositories import (
    CardRepository,
)
from examples.fastapi_agile_project_planner.app.backend.logging_setup import _LOG_DIR
from examples.fastapi_agile_project_planner.app.backend.main import create_app
from examples.fastapi_agile_project_planner.app.backend.services import (
    KanbanService,
    ServiceStatus,
)


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
    # KanbanController.add_column() appends this hint specifically to the
    # "conflict" case — it describes the duplicate-name rule, not the
    # empty-name one (see test_add_empty_column_name_does_not_get_the_
    # duplicate_name_hint below for the case this used to be misfired on).
    assert "hint: column names must be unique per board" in dup.json()["error"]["message"]


def test_add_empty_column_name_does_not_get_the_duplicate_name_hint(client):
    """A blank name is validation_failed, not conflict — it must not pick
    up add_column()'s "unique per board" hint, which describes a different
    failure than "the name is empty"."""
    board = _create_board(client)

    resp = client.post(f"/api/boards/{board['id']}/columns", json={"name": "   "})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["message"] == "Column name must not be empty"
    assert "hint" not in body["error"]["message"]


async def test_concurrent_add_column_with_same_name_only_one_succeeds(tmp_path: Path):
    """Regression test for a TOCTOU race: add_column()'s duplicate-name
    check (kanban_service.py) reads existing columns before either
    concurrent call commits, so an in-app pre-check alone can't stop two
    simultaneous requests from both passing it. columns(board_id, name)
    has a real UNIQUE constraint (tables/column_table.py) as the actual
    guarantee — session_scope translates the loser's IntegrityError into
    StorageConflict (atlasboxpy_db's quantum_registry.py), which
    translate_db_errors (services/results.py) turns into a "conflict"
    ServiceResult instead of an uncaught exception.

    Uses a real file-backed SQLite database, not the `client` fixture's
    shared in-memory `StaticPool` one: `StaticPool` hands out the same
    physical connection to every checkout, which breaks transaction
    isolation between two genuinely concurrent writers on this same
    connection and would make this test's result meaningless — a
    file-backed database gives each session its own real connection, the
    same as production.
    """
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    await init_db(engine)
    create_app(session_factory=make_session_factory(engine))
    await set_simulation(None)
    service = KanbanService()

    board = await service.create_board("Race board")
    board_id = board.result.data["id"]

    results = await asyncio.gather(
        service.add_column(board_id, "Duplicate"),
        service.add_column(board_id, "Duplicate"),
    )
    assert sorted(r.status.value for r in results) == ["error", "success"]
    conflict = next(r for r in results if r.status == ServiceStatus.ERROR)
    assert conflict.error_code == "conflict"

    final = await service.get_board(board_id)
    names = [c["name"] for c in final.result.data["columns"]]
    assert names.count("Duplicate") == 1

    await engine.dispose()


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
    assert moved.status_code == 202  # event-fired: a move is a domain event, not just a data read
    assert moved.json()["status"] == "event-fired"
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


def test_delete_board_fails_safe_when_the_cascade_delete_fails_after_the_board_is_gone(
    client, monkeypatch
):
    """delete_board() deletes the board row first, then cascades to its
    cards/columns — deliberately, so a failure partway through the
    cascade still leaves the board itself already gone (row deleted,
    cache invalidated) instead of an orphaned board that still looks
    intact and returns stale data. Simulates a failure in just the
    cascade step — the db_simulation toggle only offers a coarser,
    whole-database-down failure — by monkeypatching
    CardRepository.delete_for_board directly."""
    board = _create_board(client)
    board_id = board["id"]

    async def _boom(self, board_id: str) -> None:
        raise StorageUnavailable("simulated cascade failure")

    monkeypatch.setattr(CardRepository, "delete_for_board", _boom)
    resp = client.delete(f"/api/boards/{board_id}")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"
    monkeypatch.undo()

    # The board itself is already gone despite the cascade failing above
    # — not a stale "still exists with all its data" response.
    assert client.get(f"/api/boards/{board_id}").status_code == 404


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
    assert 'request={"name": "Logged board"}' in create_line
    assert '"status": "success"' in create_line


def test_traffic_log_redacts_the_session_token(client):
    """find_related_tasks_by_card's `token` is a session-token/JWT
    stand-in (see UserSessionService's docstring) — it must never appear
    in cleartext in the persistent, unencrypted traffic log."""
    client.post("/api/cards/tag-by-team", json={"token": "demo-token-alice"})

    log_path = _LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_atlasboxpy_controller.log"
    lines = log_path.read_text().splitlines()
    line = next(line for line in reversed(lines) if "find_related_tasks_by_card" in line)
    assert "demo-token-alice" not in line
    assert '"token": "***REDACTED***"' in line

    not_found_line = next(line for line in reversed(lines) if "does-not-exist" in line)
    assert '"url": "/api/boards/does-not-exist"' in not_found_line
    assert '"method": "GET"' in not_found_line
    assert "method=get_board" in not_found_line
    assert "status=not_found" in not_found_line  # the DomainError's own code, not just "error"
    assert '"status": "not-found"' in not_found_line
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


def test_simulate_db_timeout_maps_to_its_own_timeout_status(client):
    # A timeout is not the same failure as a generic upstream/DB error — it
    # gets its own DomainError (TimedOutError) and its own status/response_code
    # (504/"timeout"), distinct from the 502/"api-error" case above, so a
    # caller (REST or an agent reading the envelope directly) can tell "the
    # backend is broken" apart from "the backend is just slow" without
    # string-matching the error message.
    client.post("/api/debug/db-connection", json={"enabled": True, "mode": "timeout"})
    resp = client.post("/api/boards", json={"name": "x"})
    assert resp.status_code == 504
    assert resp.json()["status"] == "timeout"
    assert resp.json()["error"]["code"] == "timeout"
    client.post("/api/debug/db-connection", json={"enabled": False})


async def test_concurrent_set_simulation_calls_are_serialized(monkeypatch):
    """set_simulation() mutates several module-level globals across
    multiple await points (db_simulation.py); without its `_lock`, two
    concurrent toggle calls (two overlapping POST /api/debug/db-connection
    requests) can interleave and leave the simulation stuck in an
    unintended mode with a leaked, never-disposed connection.

    Forces a deterministic interleave — rather than a probabilistic stress
    test hoping asyncio scheduling happens to trigger it — by making
    AsyncEngine.connect() (the one real await point set_simulation("timeout")
    exercises) pause mid-call, and asserting no second call's own connect()
    starts until the first one has both returned AND released the lock."""
    from sqlalchemy.ext.asyncio import AsyncEngine

    from examples.fastapi_agile_project_planner.app.backend.infrastructure.database.db_connections import (
        db_simulation as sim_module,
    )

    active = 0
    max_active = 0
    real_connect = AsyncEngine.connect

    async def tracking_connect(self, *args, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        try:
            return await real_connect(self, *args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(AsyncEngine, "connect", tracking_connect)
    try:
        await asyncio.gather(
            sim_module.set_simulation("timeout"),
            sim_module.set_simulation("timeout"),
        )
        # If the lock didn't serialize these, both calls' connect() calls
        # would overlap (max_active == 2) — the exact interleave that lets
        # one call's teardown miss the other's not-yet-assigned state.
        assert max_active == 1
    finally:
        monkeypatch.undo()
        await sim_module.set_simulation(None)


def test_writes_invalidate_the_cached_board(client):
    """A write affecting a board (adding a column here) invalidates that
    board's columns cache entry in ColumnRepository, so the next read
    reflects the change instead of serving stale cached data."""
    board = _create_board(client, name="Invalidate me")
    assert len(client.get(f"/api/boards/{board['id']}").json()["data"]["columns"]) == 3

    client.post(f"/api/boards/{board['id']}/columns", json={"name": "Backlog"})

    refreshed = client.get(f"/api/boards/{board['id']}").json()["data"]
    assert len(refreshed["columns"]) == 4
    assert any(c["name"] == "Backlog" for c in refreshed["columns"])


def test_cached_board_survives_db_being_down(client):
    """BoardRepository/ColumnRepository/CardRepository each cache their own
    read (get_by_id / list_for_board / list_for_board) — a board that's
    already been read (creating one populates all three via
    create_board()'s own trailing get_board() call) keeps serving
    correctly even while the (simulated) database is down, since
    KanbanService's assembly never has to reach it. This is the payoff of
    caching in each repository, not just a memory-saving trick."""
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
            assert degraded.status_code == 207  # NOT 502 — the fallback absorbed the failure
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


def test_find_related_tasks_by_card_rejects_an_unknown_token(client):
    resp = client.post("/api/cards/tag-by-team", json={"token": "not-a-real-token"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_find_related_tasks_by_card_tags_cards_via_the_full_multi_service_pipeline(
    tmp_path: Path,
):
    """The worked example of KanbanController orchestrating multiple
    services (UserSessionService -> KanbanService -> TaskAgentService ->
    KanbanService), not just multiple repositories the way KanbanService
    itself does. TaskAgentService's deterministic stub (see its own
    module docstring) tags "bug" for a title/description containing
    "bug"/"fix"/"crash" — a real agent call would replace it without
    changing this endpoint's contract.

    Uses a real file-backed SQLite database, not the `client` fixture's
    shared in-memory `StaticPool` one — `update_card_tags` writes several
    cards concurrently (`asyncio.gather`), and `StaticPool` hands out the
    same physical connection to every checkout, which breaks transaction
    isolation between genuinely concurrent writers (see the identical
    reasoning on `test_concurrent_add_column_with_same_name_only_one_succeeds`
    above) — it silently dropped one card's tag update entirely. A
    file-backed database gives each session its own real connection, the
    same as production.
    """
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'orchestration.db'}")
    await init_db(engine)
    app = create_app(session_factory=make_session_factory(engine))
    await set_simulation(None)
    with TestClient(app) as client:
        board = _create_board(client)
        column_id = board["columns"][0]["id"]
        client.post(
            f"/api/boards/{board['id']}/cards",
            json={"column_id": column_id, "title": "bug fix", "description": "crashes on login"},
        )
        client.post(
            f"/api/boards/{board['id']}/cards",
            json={
                "column_id": column_id,
                "title": "homepage",
                "description": "update banner copy",
            },
        )

        resp = client.post("/api/cards/tag-by-team", json={"token": "demo-token-alice"})
        assert resp.status_code == 200
        tags_by_title = {c["title"]: c["tags"] for c in resp.json()["data"]}
        assert tags_by_title["bug fix"] == ["bug"]
        assert tags_by_title["homepage"] == []

        # Tags are actually persisted, not just returned in this one response.
        refreshed = client.get(f"/api/boards/{board['id']}").json()["data"]
        refreshed_cards = [c for col in refreshed["columns"] for c in col["cards"]]
        assert {c["title"]: c["tags"] for c in refreshed_cards}["bug fix"] == ["bug"]

    await set_simulation(None)
    await engine.dispose()
