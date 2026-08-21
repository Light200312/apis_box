import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from browser_manager import BrowserConnectionError, BrowserManager
from chatgpt_automation import ChatGPTAutomation
from claude_automation import ClaudeAutomation
from gemini_automation import GeminiAutomation
from grok_automation import GrokAutomation
from deepseek_automation import DeepSeekAutomation


Provider = Literal["chatgpt", "claude", "gemini", "grok", "deepseek"]

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
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
    provider: Provider
    response: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await browser_manager.close()


app = FastAPI(title="AI Automation Assistant API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def status() -> dict[str, object]:
    return await browser_manager.get_status()


@app.post("/api/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    if request.provider == "chatgpt":
        async with browser_manager.lock:
            try:
                response = await chatgpt.ask(request.prompt, _set_status)
            except BrowserConnectionError as error:
                logging.getLogger(__name__).warning("ChatGPT browser unavailable: %s", error)
                raise HTTPException(status_code=503, detail=str(error)) from error
            except Exception as error:
                logging.getLogger(__name__).exception("ChatGPT request failed")
                raise HTTPException(
                    status_code=503,
                    detail=str(error) or "ChatGPT automation could not complete the request.",
                ) from error
        return AskResponse(provider=request.provider, response=response)

    if request.provider == "claude":
        async with browser_manager.lock:
            try:
                response = await claude.ask_claude(request.prompt)
            except BrowserConnectionError as error:
                logging.getLogger(__name__).warning("Claude browser unavailable: %s", error)
                raise HTTPException(status_code=503, detail=str(error)) from error
            except Exception as error:
                logging.getLogger(__name__).exception("Claude request failed")
                raise HTTPException(
                    status_code=503,
                    detail=str(error) or "Claude automation could not complete the request.",
                ) from error
        return AskResponse(provider=request.provider, response=response)

    if request.provider == "gemini":
        async with browser_manager.lock:
            try:
                response = await gemini.ask_gemini(request.prompt)
            except BrowserConnectionError as error:
                logging.getLogger(__name__).warning("Gemini browser unavailable: %s", error)
                raise HTTPException(status_code=503, detail=str(error)) from error
            except Exception as error:
                logging.getLogger(__name__).exception("Gemini request failed")
                raise HTTPException(
                    status_code=503,
                    detail=str(error) or "Gemini automation could not complete the request.",
                ) from error
        return AskResponse(provider=request.provider, response=response)

    if request.provider == "grok":
        async with browser_manager.lock:
            try:
                response = await grok.ask_grok(request.prompt)
            except BrowserConnectionError as error:
                logging.getLogger(__name__).warning("Grok browser unavailable: %s", error)
                raise HTTPException(status_code=503, detail=str(error)) from error
            except Exception as error:
                logging.getLogger(__name__).exception("Grok request failed")
                raise HTTPException(
                    status_code=503,
                    detail=str(error) or "Grok automation could not complete the request.",
                ) from error
        return AskResponse(provider=request.provider, response=response)

    if request.provider == "deepseek":
        async with browser_manager.lock:
            try:
                response = await deepseek.ask_deepseek(request.prompt)
            except BrowserConnectionError as error:
                logging.getLogger(__name__).warning("DeepSeek browser unavailable: %s", error)
                raise HTTPException(status_code=503, detail=str(error)) from error
            except Exception as error:
                logging.getLogger(__name__).exception("DeepSeek request failed")
                raise HTTPException(
                    status_code=503,
                    detail=str(error) or "DeepSeek automation could not complete the request.",
                ) from error
        return AskResponse(provider=request.provider, response=response)

    provider_names = {
        "chatgpt": "ChatGPT",
        "claude": "Claude",
        "gemini": "Gemini",
        "grok": "Grok",
        "deepseek": "DeepSeek",
    }
    provider_name = provider_names[request.provider]
    return AskResponse(
        provider=request.provider,
        response=(
            f"Mock response from {provider_name}. "
            "Browser automation will be connected in the next step."
        ),
    )


async def _set_status(message: str) -> None:
    browser_manager.status = message
    logging.getLogger(__name__).info(message)
