import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from anthropic_adapter import message_response, prompt_from_messages, stream_response
from automation_errors import ResponseUncertainError, SafeToFallbackError
from browser_manager import BrowserConnectionError, BrowserManager
from chatgpt_automation import ChatGPTAutomation
from claude_automation import ClaudeAutomation
from deepseek_automation import DeepSeekAutomation
from gemini_automation import GeminiAutomation
from grok_automation import GrokAutomation

Provider = Literal["chatgpt", "claude", "gemini", "grok", "deepseek"]
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
browser_manager = BrowserManager()
chatgpt = ChatGPTAutomation(browser_manager)
claude = ClaudeAutomation(browser_manager)
gemini = GeminiAutomation(browser_manager)
grok = GrokAutomation(browser_manager)
deepseek = DeepSeekAutomation(browser_manager)


class AskRequest(BaseModel):
    provider: Provider
    prompt: str = Field(min_length=1)


class AskResponse(BaseModel):
    """The returned provider is the one that actually generated the text."""

    provider: Provider
    response: str
    requested_provider: Provider | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await browser_manager.close()


app = FastAPI(title="AI Automation Assistant API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def status() -> dict[str, object]:
    return await browser_manager.get_status()


async def _ask_claude_first(prompt: str) -> tuple[Provider, str]:
    """Fall back only if Claude definitely did not receive the prompt."""
    async with browser_manager.lock:
        try:
            return "claude", await claude.ask_claude(prompt)
        except (SafeToFallbackError, BrowserConnectionError) as error:
            logger.warning("Claude unavailable before submission; using ChatGPT fallback: %s", error)
            try:
                return "chatgpt", await chatgpt.ask(prompt, _set_status)
            except Exception as fallback_error:
                logger.exception("Claude and ChatGPT both failed")
                raise HTTPException(
                    status_code=503,
                    detail={
                        "message": "Claude failed before submission and ChatGPT fallback also failed.",
                        "claude_error": str(error),
                        "chatgpt_error": str(fallback_error),
                    },
                ) from fallback_error
        except ResponseUncertainError as error:
            logger.warning("Claude may already have received the prompt; fallback suppressed: %s", error)
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Claude may have received the prompt; fallback was suppressed to avoid duplicate work.",
                    "claude_error": str(error),
                },
            ) from error


async def _ask_provider(provider: Provider, prompt: str) -> tuple[Provider, str]:
    if provider == "claude":
        return await _ask_claude_first(prompt)
    automations: dict[Provider, Any] = {
        "chatgpt": lambda: chatgpt.ask(prompt, _set_status),
        "gemini": lambda: gemini.ask_gemini(prompt),
        "grok": lambda: grok.ask_grok(prompt),
        "deepseek": lambda: deepseek.ask_deepseek(prompt),
    }
    async with browser_manager.lock:
        try:
            return provider, await automations[provider]()
        except BrowserConnectionError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except Exception as error:
            logger.exception("%s request failed", provider)
            raise HTTPException(
                status_code=503,
                detail=str(error) or f"{provider} automation could not complete the request.",
            ) from error


@app.post("/api/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    provider, response = await _ask_provider(request.provider, request.prompt)
    return AskResponse(provider=provider, requested_provider=request.provider, response=response)


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    """Anthropic Messages text bridge for Claude Code-compatible clients."""
    try:
        payload = await request.json()
    except Exception as error:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    model, messages = payload.get("model"), payload.get("messages")
    if not isinstance(model, str) or not model.strip():
        raise HTTPException(status_code=400, detail="model is required.")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be an array.")
    try:
        prompt = prompt_from_messages(payload.get("system"), messages)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    provider, text = await _ask_claude_first(prompt)
    response = message_response(text, model, provider)
    headers = {"X-Apis-Box-Provider": provider, "X-Apis-Box-Tool-Use": "unsupported"}
    if payload.get("stream") is True:
        return StreamingResponse(stream_response(response), media_type="text/event-stream", headers=headers)
    return JSONResponse(response, headers=headers)


async def _set_status(message: str) -> None:
    browser_manager.status = message
    logger.info(message)
