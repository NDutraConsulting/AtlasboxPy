from typing import Any

from validator_gateway import BaseController


class DegradedBoardController(BaseController):
    """Serves a minimal, clearly-marked degraded response when the primary
    BoardController can't reach "the database". See
    board_validator_gateway.py's UPSTREAM_UNAVAILABLE case, which redirects
    a failed read here instead of just reporting the outage — this is a
    real, separate controller/gateway pair, not a patched-over error."""

    async def get_degraded_board(self, board_id: str) -> dict[str, Any]:
        return {
            "id": board_id,
            "name": "(unavailable — degraded response)",
            "columns": [],
            "degraded": True,
        }
