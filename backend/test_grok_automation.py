import asyncio

import grok_automation
from grok_automation import GrokAutomation


def assistant(text: str, key: str = "new") -> dict:
    return {"id": key, "text": text, "is_assistant": True}


def test_selects_new_assistant_response():
    selected = GrokAutomation._select_response_candidate(
        [
            {"id": "old", "text": "previous", "is_assistant": True},
            assistant("answer", "new"),
        ],
        {"old": "previous"},
    )

    assert selected == assistant("answer", "new")


def test_ignores_non_assistant_status_candidate():
    selected = GrokAutomation._select_response_candidate(
        [{"id": "status", "text": "Generating", "is_assistant": False}],
        {},
    )

    assert selected is None


class SequenceGrokAutomation(GrokAutomation):
    def __init__(self, candidates, states):
        self.candidates = iter(candidates)
        self.states = iter(states)

    async def _get_response_candidates(self, _page):
        return next(self.candidates)

    async def _get_composer_state(self, _page):
        return next(self.states)


def test_waits_for_generation_to_finish(monkeypatch):
    monkeypatch.setattr(grok_automation, "GROK_POLL_INTERVAL_SECONDS", 0)
    automation = SequenceGrokAutomation(
        [[assistant("short")]] * 4,
        [{"generation_active": True}] * 2 + [{"generation_active": False}] * 2,
    )

    assert asyncio.run(automation._read_new_response(None, {})) == "short"
