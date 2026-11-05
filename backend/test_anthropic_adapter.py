import asyncio
import json

import pytest
from fastapi import HTTPException

import main
from anthropic_adapter import message_response, prompt_from_messages, stream_response
from automation_errors import ResponseUncertainError, SafeToFallbackError


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def test_prompt_translation_keeps_text_and_tool_results():
    prompt = prompt_from_messages(
        "Follow project rules.",
        [
            {"role": "user", "content": [{"type": "text", "text": "Read app.py"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "I will inspect it."}]},
            {"role": "user", "content": [{"type": "tool_result", "content": "file contents"}]},
        ],
    )
    assert "System instructions" in prompt
    assert "Read app.py" in prompt
    assert "Tool result:\nfile contents" in prompt


def test_sse_has_complete_messages_lifecycle():
    response = message_response("hello", "claude-test", "claude")
    body = "".join(asyncio.run(_collect(stream_response(response))))
    assert "event: message_start" in body
    assert "event: content_block_delta" in body
    assert '"text":"hello"' in body
    assert "event: message_stop" in body


async def _collect(iterator):
    return [item async for item in iterator]


def test_claude_safe_failure_falls_back_and_reports_actual_provider(monkeypatch):
    async def claude_failure(_prompt):
        raise SafeToFallbackError("tab missing")

    async def chatgpt_answer(_prompt, _status):
        return "fallback answer"

    monkeypatch.setattr(main.claude, "ask_claude", claude_failure)
    monkeypatch.setattr(main.chatgpt, "ask", chatgpt_answer)
    result = asyncio.run(main.ask(main.AskRequest(provider="claude", prompt="hello")))
    assert result.provider == "chatgpt"
    assert result.requested_provider == "claude"
    assert result.response == "fallback answer"


def test_uncertain_claude_failure_does_not_submit_to_fallback(monkeypatch):
    called = False

    async def claude_failure(_prompt):
        raise ResponseUncertainError("response timed out")

    async def chatgpt_answer(_prompt, _status):
        nonlocal called
        called = True
        return "must not happen"

    monkeypatch.setattr(main.claude, "ask_claude", claude_failure)
    monkeypatch.setattr(main.chatgpt, "ask", chatgpt_answer)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main._ask_claude_first("hello"))
    assert error.value.status_code == 503
    assert called is False


def test_messages_endpoint_returns_anthropic_text_response(monkeypatch):
    async def answer(_prompt):
        return "claude", "browser answer"

    monkeypatch.setattr(main, "_ask_claude_first", answer)
    result = asyncio.run(
        main.anthropic_messages(
            JsonRequest(
                {
                    "model": "claude-test",
                    "max_tokens": 32,
                    "messages": [{"role": "user", "content": "hello"}],
                }
            )
        )
    )
    data = json.loads(result.body)
    assert data["type"] == "message"
    assert data["content"] == [{"type": "text", "text": "browser answer"}]
    assert result.headers["x-apis-box-provider"] == "claude"


def test_messages_endpoint_validates_required_fields():
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.anthropic_messages(JsonRequest({"messages": []})))
    assert error.value.status_code == 400
