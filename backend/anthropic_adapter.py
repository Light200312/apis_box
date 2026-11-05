"""Small Anthropic Messages API adapter for the local browser-backed providers.

This intentionally supports text responses only.  A rendered browser response is
not a trustworthy source of Anthropic ``tool_use`` blocks, so it never invents
them.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any


def prompt_from_messages(system: Any, messages: list[dict[str, Any]]) -> str:
    """Flatten Anthropic text/content blocks for the browser chat composer."""
    parts: list[str] = []
    if isinstance(system, str) and system.strip():
        parts.append(f"System instructions:\n{system.strip()}")
    elif isinstance(system, list):
        system_text = "\n".join(_content_to_text(block) for block in system)
        if system_text.strip():
            parts.append(f"System instructions:\n{system_text.strip()}")

    for message in messages:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = _content_to_text(message.get("content"))
        if content.strip():
            parts.append(f"{role.capitalize()}:\n{content.strip()}")
    if not parts:
        raise ValueError("messages must contain at least one non-empty text block")
    return "\n\n".join(parts)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    text: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and isinstance(block.get("text"), str):
            text.append(block["text"])
        elif kind == "tool_result":
            text.append("Tool result:\n" + _content_to_text(block.get("content")))
    return "\n".join(item for item in text if item)


def message_response(text: str, model: str, _provider: str) -> dict[str, Any]:
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


async def stream_response(response: dict[str, Any]) -> AsyncIterator[str]:
    """Emit the required Messages SSE lifecycle as one text delta."""
    message = {key: value for key, value in response.items() if key != "content"}
    message["content"] = []
    events = (
        ("message_start", {"type": "message_start", "message": message}),
        (
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        ),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": response["content"][0]["text"]}},
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 0}},
        ),
        ("message_stop", {"type": "message_stop"}),
    )
    for event, body in events:
        yield f"event: {event}\ndata: {json.dumps(body, separators=(',', ':'))}\n\n"
