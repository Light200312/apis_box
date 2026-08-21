import asyncio

import claude_automation
from claude_automation import ClaudeAutomation


def assistant_candidate(text: str, key: str = "assistant-index:1") -> dict:
    return {
        "id": key,
        "text": text,
        "is_assistant": True,
        "is_transient": False,
        "attributes": {
            "tag_name": "DIV",
            "data_testid": None,
        },
    }


def transient_candidate(text: str) -> dict:
    return {
        "id": "status:1",
        "text": text,
        "is_assistant": False,
        "is_transient": True,
    }


class SequenceClaudeAutomation(ClaudeAutomation):
    def __init__(self, candidates, composer_states):
        self.candidates = iter(candidates)
        self.composer_states = iter(composer_states)

    async def _get_response_candidates(self, _page):
        return next(self.candidates)

    async def _get_composer_state(self, _page):
        return next(self.composer_states)


def test_select_response_candidate_returns_latest_changed_message():
    candidates = [
        {"key": "first", "text": "initial"},
        {"key": "second", "text": "answer part 1"},
        {"key": "third", "text": "answer part 2"},
    ]

    selected = ClaudeAutomation._select_response_candidate(
        candidates,
        {"first": "initial"},
    )

    assert selected is not None
    assert selected["key"] == "third"


def test_select_response_candidate_ignores_transient_generation_status():
    selected = ClaudeAutomation._select_response_candidate(
        [
            transient_candidate("Mulling"),
            assistant_candidate("The actual answer"),
        ],
        {},
    )

    assert selected is not None
    assert selected["text"] == "The actual answer"


def test_select_response_candidate_ignores_unknown_transient_activity_phrase():
    selected = ClaudeAutomation._select_response_candidate(
        [transient_candidate("Claude is quietly rearranging the stars")],
        {},
    )

    assert selected is None


def test_read_new_response_accepts_short_legitimate_answer(monkeypatch):
    monkeypatch.setattr(claude_automation, "CLAUDE_POLL_INTERVAL_SECONDS", 0)
    automation = SequenceClaudeAutomation(
        [[assistant_candidate("7")]] * 3,
        [{"generation_active": False}] * 3,
    )

    response = asyncio.run(automation._read_new_response(None, [], {}))

    assert response == "7"


def test_read_new_response_returns_normal_multiline_response(monkeypatch):
    monkeypatch.setattr(claude_automation, "CLAUDE_POLL_INTERVAL_SECONDS", 0)
    response_text = "First line\n\nSecond line"
    automation = SequenceClaudeAutomation(
        [[assistant_candidate(response_text)]] * 3,
        [{"generation_active": False}] * 3,
    )

    response = asyncio.run(automation._read_new_response(None, [], {}))

    assert response == response_text


def test_read_new_response_waits_when_text_is_stable_but_generation_active(monkeypatch):
    monkeypatch.setattr(claude_automation, "CLAUDE_POLL_INTERVAL_SECONDS", 0)
    response_text = "Stable so far"
    automation = SequenceClaudeAutomation(
        [[assistant_candidate(response_text)]] * 4,
        [
            {"generation_active": True},
            {"generation_active": True},
            {"generation_active": True},
            {"generation_active": False},
        ],
    )

    response = asyncio.run(automation._read_new_response(None, [], {}))

    assert response == response_text


def test_clean_response_text_removes_claude_label_prefix():
    cleaned = ClaudeAutomation._clean_response_text("Claude said\n8")

    assert cleaned == "8"


def test_clean_response_text_removes_claude_responded_label_prefix():
    cleaned = ClaudeAutomation._clean_response_text("Claude responded:\n8")

    assert cleaned == "8"


def test_clean_response_text_preserves_full_response():
    response = "Claude responded: First line\n\nSecond line"

    assert ClaudeAutomation._clean_response_text(response) == "First line\n\nSecond line"
