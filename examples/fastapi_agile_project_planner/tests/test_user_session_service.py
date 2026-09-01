"""UserSessionService is a deliberate stub (see its own module
docstring) — these tests cover the seeded lookup behavior, not real
JWT/session semantics, which don't exist here."""

from examples.fastapi_agile_project_planner.app.backend.services import (
    UserSession,
    UserSessionService,
)


async def test_known_token_returns_the_seeded_session():
    service = UserSessionService()
    session = await service.get_user("demo-token-alice")
    assert session == UserSession(user_id="user-alice", team_id="team-agile", username="alice")


async def test_unknown_token_returns_none():
    service = UserSessionService()
    assert await service.get_user("not-a-real-token") is None


async def test_custom_session_store_can_be_injected_for_testing():
    custom = {"my-token": UserSession(user_id="u1", team_id="t1", username="test-user")}
    service = UserSessionService(sessions=custom)
    session = await service.get_user("my-token")
    assert session is not None
    assert session.user_id == "u1"
    assert await service.get_user("demo-token-alice") is None  # seed data not used
