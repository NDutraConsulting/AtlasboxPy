"""TaskAgentService is a deliberate stub for a real AI-agent call (see
its own module docstring) — these tests cover the deterministic
keyword-heuristic behavior actually implemented, not agent/LLM
semantics, which don't exist here."""

from examples.fastapi_agile_project_planner.app.backend.services import TaskAgentService


async def test_tags_a_card_matching_a_bug_keyword():
    service = TaskAgentService()
    result = await service.tag_cards([{"id": "c1", "title": "Fix login bug", "description": ""}])
    assert result == {"c1": ["bug"]}


async def test_tags_a_card_matching_multiple_keywords():
    service = TaskAgentService()
    result = await service.tag_cards(
        [{"id": "c1", "title": "Urgent bug in checkout", "description": ""}]
    )
    assert result == {"c1": ["bug", "priority"]}


async def test_card_matching_no_keywords_gets_no_tags():
    service = TaskAgentService()
    result = await service.tag_cards(
        [{"id": "c1", "title": "Update homepage banner", "description": ""}]
    )
    assert result == {"c1": []}


async def test_matches_are_case_insensitive_and_check_description_too():
    service = TaskAgentService()
    result = await service.tag_cards(
        [{"id": "c1", "title": "Something", "description": "Needs DOCUMENTATION"}]
    )
    assert result == {"c1": ["docs"]}


async def test_tags_multiple_cards_independently():
    service = TaskAgentService()
    result = await service.tag_cards(
        [
            {"id": "c1", "title": "Fix crash", "description": ""},
            {"id": "c2", "title": "Improve testing coverage", "description": ""},
        ]
    )
    assert result == {"c1": ["bug"], "c2": ["testing"]}


async def test_matching_is_whole_word_not_substring():
    """A keyword embedded inside an unrelated word must never match:
    "prefix" contains "fix" but isn't about a bug, "contest"/"latest"
    contain "test" but aren't about testing, "doctor"/"docking" contain
    "doc" but aren't about documentation."""
    service = TaskAgentService()
    cards = [
        {"id": "c1", "title": "Redesign login prefix flow", "description": ""},
        {"id": "c2", "title": "Design contest submission", "description": ""},
        {"id": "c3", "title": "Update the latest banner", "description": ""},
        {"id": "c4", "title": "Doctor availability lookup", "description": ""},
        {"id": "c5", "title": "Fix the docking station", "description": ""},
    ]
    result = await service.tag_cards(cards)
    assert result == {"c1": [], "c2": [], "c3": [], "c4": [], "c5": ["bug"]}
    # c5 is legitimately tagged "bug" for the whole word "fix" — "docking"
    # is still correctly *not* matched against "doc".


async def test_missing_description_key_does_not_raise():
    service = TaskAgentService()
    result = await service.tag_cards([{"id": "c1", "title": "urgent"}])
    assert result == {"c1": ["priority"]}


async def test_no_cards_returns_empty_dict():
    service = TaskAgentService()
    assert await service.tag_cards([]) == {}
