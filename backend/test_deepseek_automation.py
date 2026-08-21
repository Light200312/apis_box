import asyncio

import deepseek_automation
from deepseek_automation import DeepSeekAutomation


def assistant(text: str, key: str = "new") -> dict:
    return {"id": key, "text": text, "is_assistant": True}


def test_selects_new_assistant_response():
    selected = DeepSeekAutomation._select_response_candidate(
        [{"id": "old", "text": "previous", "is_assistant": True}, assistant("answer")],
        {"old": "previous"},
    )

    assert selected == assistant("answer")


def test_ignores_non_assistant_candidate():
    selected = DeepSeekAutomation._select_response_candidate(
        [{"id": "status", "text": "Thinking", "is_assistant": False}],
        {},
    )

    assert selected is None


class SequenceDeepSeekAutomation(DeepSeekAutomation):
    def __init__(self, candidates, states):
        self.candidates = iter(candidates)
        self.states = iter(states)

    async def _get_response_candidates(self, _page):
        return next(self.candidates)

    async def _get_composer_state(self, _page):
        return next(self.states)


def test_waits_for_generation_to_finish(monkeypatch):
    monkeypatch.setattr(deepseek_automation, "DEEPSEEK_POLL_INTERVAL_SECONDS", 0)
    automation = SequenceDeepSeekAutomation(
        [[assistant("short")]] * 4,
        [{"generation_active": True}] * 2 + [{"generation_active": False}] * 2,
    )

    assert asyncio.run(automation._read_new_response(None, {})) == "short"
