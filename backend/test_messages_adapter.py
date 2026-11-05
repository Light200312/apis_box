import asyncio

import main


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def valid_payload(**overrides):
    payload = {
        "model": "claude-test",
        "max_tokens": 128,
        "messages": [{"role": "user", "content": "Say hello."}],
    }
    payload.update(overrides)
    return payload


def test_messages_uses_claude_first(monkeypatch):
    async def fake_route(prompt):
        assert "User:\nSay hello." in prompt
        return "claude", "Hello from Claude"

    monkeypatch.setattr(main, "_ask_claude_first", fake_route)
    response = asyncio.run(main.anthropic_messages(JsonRequest(valid_payload())))

    assert response.status_code == 200
    assert response.headers["x-apis-box-provider"] == "claude"
    assert b'"text":"Hello from Claude"' in response.body
    assert b'"stop_reason":"end_turn"' in response.body


def test_messages_streams_anthropic_events(monkeypatch):
    async def fake_route(_prompt):
        return "chatgpt", "Fallback answer"

    monkeypatch.setattr(main, "_ask_claude_first", fake_route)
    response = asyncio.run(main.anthropic_messages(JsonRequest(valid_payload(stream=True))))
    body = "".join(asyncio.run(collect(response.body_iterator)))

    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: message_start" in body
    assert "event: content_block_delta" in body
    assert "Fallback answer" in body
    assert "event: message_stop" in body


async def collect(iterator):
    return [item async for item in iterator]


def test_fallback_is_used_once_for_retriable_claude_failure(monkeypatch):
    calls = []

    class FakeClaude:
        async def ask_claude(self, _prompt):
            calls.append("claude")
            raise main.SafeToFallbackError("Claude requires login")

    class FakeChatGPT:
        async def ask(self, _prompt, _set_status):
            calls.append("chatgpt")
            return "Answer from fallback"

    monkeypatch.setattr(main, "claude", FakeClaude())
    monkeypatch.setattr(main, "chatgpt", FakeChatGPT())
    provider, answer = asyncio.run(main._ask_claude_first("prompt"))

    assert (provider, answer) == ("chatgpt", "Answer from fallback")
    assert calls == ["claude", "chatgpt"]


def test_uncertain_claude_submission_does_not_fallback(monkeypatch):
    calls = []

    class FakeClaude:
        async def ask_claude(self, _prompt):
            calls.append("claude")
            raise main.ResponseUncertainError("response reader failed after submission")

    class FakeChatGPT:
        async def ask(self, _prompt, _set_status):
            calls.append("chatgpt")
            return "must not run"

    monkeypatch.setattr(main, "claude", FakeClaude())
    monkeypatch.setattr(main, "chatgpt", FakeChatGPT())

    try:
        asyncio.run(main._ask_claude_first("prompt"))
    except main.HTTPException as error:
        assert error.status_code == 503
    else:
        raise AssertionError("Expected HTTPException")
    assert calls == ["claude"]
