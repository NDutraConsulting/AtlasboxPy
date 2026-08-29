from validator_gateway import RateLimitedError, UpstreamServiceError


class SyncService:
    """Simulates a flaky downstream directory service.

    - user ids starting with "flaky" fail their first 2 calls, then succeed
      (demonstrates RETRY recovering within a single gateway.handle() call).
    - user ids starting with "always-fails" never succeed on their own
      (demonstrates RETRY exhausting, then REDIRECT).
    - user ids starting with "quota-" hit a rate limit with no retry policy
      of its own — just an immediate QUEUE handoff.
    """

    def __init__(self) -> None:
        self._call_counts: dict[str, int] = {}

    async def sync_user(self, user_id: str) -> dict:
        count = self._call_counts.get(user_id, 0) + 1
        self._call_counts[user_id] = count

        if user_id.startswith("quota-"):
            raise RateLimitedError(f"sync quota exceeded for {user_id}")
        if user_id.startswith("always-fails"):
            raise UpstreamServiceError("directory service permanently down")
        if user_id.startswith("flaky") and count <= 2:
            raise UpstreamServiceError(f"directory service unavailable (attempt {count})")
        return {"id": user_id, "synced": True}
