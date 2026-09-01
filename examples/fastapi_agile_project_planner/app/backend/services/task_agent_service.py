"""TaskAgentService — a deliberate stub standing in for a real AI-agent
call. `tag_cards` currently tags via a small deterministic
keyword-matching heuristic over each card's title/description, not an
LLM — this is the integration point where a real agent call belongs
once one is built (see this app's docs/decisions.md for the ADR on why
this is a stub for now, not an unfinished feature). Swapping the
heuristic in `_infer_tags` for a real prompt/completion call changes
nothing about this class's public contract: `tag_cards` still takes
cards and returns `{card_id: [tags]}`.

Owns exactly one bounded concern — turning card content into tags — and
never calls KanbanService or UserSessionService itself; orchestrating
across services is KanbanController's job (see
KanbanController.find_related_tasks_by_card).
"""

from __future__ import annotations

import re
from typing import Any

from atlasboxpy_service import BaseService

_KEYWORD_TAGS: dict[str, str] = {
    "bug": "bug",
    "fix": "bug",
    "error": "bug",
    "crash": "bug",
    "urgent": "priority",
    "asap": "priority",
    "critical": "priority",
    "test": "testing",
    "testing": "testing",
    "doc": "docs",
    "docs": "docs",
    "documentation": "docs",
}

# Whole-word matching, not substring: "prefix" must never match "fix",
# "contest"/"latest" must never match "test", "doctor"/"docking" must
# never match "doc" — a plain `keyword in text` check matched all of
# those wrongly.
_WORD_RE = re.compile(r"[a-z]+")


def _infer_tags(title: str, description: str) -> list[str]:
    words = set(_WORD_RE.findall(f"{title} {description}".lower()))
    tags: list[str] = []
    for keyword, tag in _KEYWORD_TAGS.items():
        if keyword in words and tag not in tags:
            tags.append(tag)
    return tags


class TaskAgentService(BaseService):
    async def tag_cards(self, cards: list[dict[str, Any]]) -> dict[str, list[str]]:
        return {
            card["id"]: _infer_tags(card.get("title", ""), card.get("description", ""))
            for card in cards
        }
