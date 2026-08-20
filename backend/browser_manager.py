import asyncio
import logging
import os
import subprocess
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright


logger = logging.getLogger(__name__)
CDP_ENDPOINT = "http://127.0.0.1:9222"
CHATGPT_URL_PARTS = ("chatgpt.com", "chat.openai.com")


class BrowserConnectionError(RuntimeError):
    pass


class BrowserManager:
    """Owns the single persistent Playwright context used by browser adapters."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()
        self._connection_blocked = False
        self.status = "Chrome not connected"

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def get_or_start(self) -> BrowserContext:
        if self._browser and self._browser.is_connected() and self._context:
            return self._context

        if self._browser or self._context:
            self._mark_disconnected()

        if self._connection_blocked:
            raise BrowserConnectionError(self._unavailable_message())

        logger.info("[BROWSER] Connecting to Chrome CDP...")
        self.status = "Connecting to Chrome..."
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(
                CDP_ENDPOINT
            )
            if not self._browser.contexts:
                raise BrowserConnectionError("Connected Chrome has no browser context.")
            self._context = self._browser.contexts[0]
        except BrowserConnectionError:
            self._connection_blocked = True
            await self._reset_connection()
            raise
        except Exception as error:
            self._connection_blocked = True
            await self._reset_connection()
            self.status = "Chrome unavailable"
            logger.warning("[BROWSER] Chrome unavailable")
            raise BrowserConnectionError(self._unavailable_message()) from error

        logger.info("[BROWSER] Connected to Chrome")
        self.status = "Chrome connected"
        return self._context

    async def get_or_create_page(self, url: str) -> Page:
        context = await self.get_or_start()
        for page in context.pages:
            if any(part in page.url for part in CHATGPT_URL_PARTS):
                logger.info("[BROWSER] ChatGPT tab found")
                return page

        logger.info("[BROWSER] ChatGPT tab created")
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        return page

    async def bring_to_foreground(self, page: Page) -> None:
        await page.bring_to_front()
        if os.name == "posix":
            try:
                subprocess.run(
                    ["wmctrl", "-a", "ChatGPT"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    async def close(self) -> None:
        # Chrome is user-owned; stop only Playwright's attachment.
        self._context = None
        self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self.status = "Chrome not connected"

    async def get_status(self) -> dict[str, object]:
        browser_connected = bool(self._browser and self._browser.is_connected())
        chatgpt_tab = None
        chatgpt_logged_in = None
        if browser_connected and self._context:
            for page in self._context.pages:
                if any(part in page.url for part in CHATGPT_URL_PARTS):
                    chatgpt_tab = True
                    chatgpt_logged_in = (
                        "/auth/" not in page.url
                        and "/login" not in page.url
                        and await page.locator(
                            '#prompt-textarea[contenteditable="true"]'
                        ).count() > 0
                    )
                    break
            if chatgpt_tab is None:
                chatgpt_tab = False
                chatgpt_logged_in = False
        return {
            "status": self.status,
            "chrome": "connected" if browser_connected else "disconnected",
            "chatgpt_tab": chatgpt_tab,
            "chatgpt_logged_in": chatgpt_logged_in,
        }

    def _mark_disconnected(self) -> None:
        self._context = None
        self._browser = None
        self._connection_blocked = True
        self.status = "Chrome disconnected"
        logger.warning("[BROWSER] Chrome disconnected")

    @staticmethod
    def _unavailable_message() -> str:
        return (
            "Automation Chrome is not available at http://127.0.0.1:9222. "
            "Start Google Chrome with the dedicated automation profile and "
            "remote debugging port 9222."
        )

    async def _reset_connection(self) -> None:
        if self._playwright:
            await self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._context = None
