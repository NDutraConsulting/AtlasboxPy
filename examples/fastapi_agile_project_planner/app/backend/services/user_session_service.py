"""UserSessionService — a deliberate stub, not an unfinished
implementation, the same "illustrative but real code shape" pattern this
app's own Cassandra/Mongo examples already use. `get_user(token)` looks
a plain token string up in a small in-memory, seeded session store —
there is no real JWT library, no signature verification, no expiry
check. Swapping this for a real session/JWT backend later means
replacing this one class's internals; nothing above it (KanbanController)
knows or cares that the lookup isn't real yet.

Owns exactly one bounded concern — "who is this caller, and what team
are they on" — nothing else. It never calls KanbanService or
TaskAgentService; orchestrating across services is
KanbanController's job (see atlasboxpy_service's README and
KanbanController.find_related_tasks_by_card for the worked example this
service participates in).
"""

from __future__ import annotations

from dataclasses import dataclass

from atlasboxpy_service import BaseService


@dataclass(frozen=True, slots=True)
class UserSession:
    user_id: str
    team_id: str
    username: str


_SEED_SESSIONS: dict[str, UserSession] = {
    "demo-token-alice": UserSession(user_id="user-alice", team_id="team-agile", username="alice"),
    "demo-token-bob": UserSession(user_id="user-bob", team_id="team-agile", username="bob"),
}


class UserSessionService(BaseService):
    def __init__(self, sessions: dict[str, UserSession] | None = None) -> None:
        super().__init__()
        self._sessions = sessions if sessions is not None else _SEED_SESSIONS

    async def get_user(self, token: str) -> UserSession | None:
        return self._sessions.get(token)
