import asyncio
import logging
import time
from typing import Awaitable, Callable

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from browser_manager import BrowserManager


logger = logging.getLogger(__name__)

CHATGPT_URL = "https://chatgpt.com/"
ASSISTANT_MESSAGES = '[data-message-author-role="assistant"]'

StatusCallback = Callable[[str], Awaitable[None]]


class ChatGPTAutomation:
    def __init__(self, browser_manager: BrowserManager) -> None:
        self.browser_manager = browser_manager

    async def ask(self, prompt: str, set_status: StatusCallback) -> str:
        ask_started = time.monotonic()
        logger.info("[TIMING] ask_start")
        page = None
        try:
            page = await self.browser_manager.get_or_create_page(CHATGPT_URL)
            await self._ensure_logged_in(page, set_status)
            await set_status("Entering prompt...")
            prompt_lookup_started = time.monotonic()
            prompt_input = await self._find_prompt_input(page)
            prompt_lookup_elapsed = time.monotonic() - prompt_lookup_started
            logger.info("[TIMING] find_prompt_input=%.3fs", prompt_lookup_elapsed)
            logger.info("[TIMING] before_prompt_insertion=%.3fs", time.monotonic() - ask_started)
            assistant_messages = page.locator(ASSISTANT_MESSAGES)
            message_count = await assistant_messages.count()
            logger.info("[TIMING] existing_assistant_messages=%d", message_count)

            prompt_fill_started = time.monotonic()
            await prompt_input.fill(prompt)
            logger.info("[TIMING] prompt_fill=%.3fs", time.monotonic() - prompt_fill_started)
            submit_started = time.monotonic()
            await prompt_input.press("Enter")
            logger.info("[TIMING] submit=%.3fs", time.monotonic() - submit_started)
            await set_status("Waiting for response...")
            return await self._read_new_response(page, message_count)
        except PlaywrightTimeoutError as error:
            logger.warning("ChatGPT automation timed out: %s", error)
            raise RuntimeError(
                "ChatGPT did not respond in time. Check the browser window and try again."
            ) from error
        except Exception:
            if page is not None and page.is_closed():
                raise RuntimeError("The ChatGPT tab was closed. Send the prompt again to reopen it.")
            raise
        finally:
            logger.info("[TIMING] total=%.3fs", time.monotonic() - ask_started)

    async def _ensure_logged_in(self, page: Page, set_status: StatusCallback) -> None:
        await set_status("Checking ChatGPT login...")
        if await self._is_logged_in(page):
            return

        logger.info("Login required")
        await set_status("ChatGPT requires login. Please complete login in the browser window. Waiting...")
        await self.browser_manager.bring_to_foreground(page)
        logger.info("Waiting for user login...")
        for _ in range(180):
            if await self._is_logged_in(page):
                logger.info("Login detected")
                await set_status("Login detected. Continuing...")
                return
            await asyncio.sleep(1)
        raise RuntimeError("ChatGPT login was not completed within the allowed time.")

    async def _is_logged_in(self, page: Page) -> bool:
        if page.is_closed():
            raise RuntimeError("The ChatGPT tab was closed. Send the prompt again to reopen it.")
        if "/auth/" in page.url or "/login" in page.url:
            return False
        try:
            await self._find_prompt_input(page, timeout=1500)
            return True
        except PlaywrightTimeoutError:
            return False

    async def _find_prompt_input(self, page: Page, timeout: int = 10000):
        locator = page.locator('#prompt-textarea[contenteditable="true"]')
        await locator.wait_for(state="visible", timeout=timeout)
        return locator

    async def _read_new_response(self, page: Page, previous_count: int) -> str:
        messages = page.locator(ASSISTANT_MESSAGES)
        wait_started = time.monotonic()
        await page.wait_for_function(
            "([selector, count]) => document.querySelectorAll(selector).length > count",
            arg=[ASSISTANT_MESSAGES, previous_count],
            timeout=120000,
        )
        response_dom_appeared_at = time.monotonic()
        logger.info(
            "[TIMING] response_dom_appeared_at=%.6f wait_new_message=%.3fs",
            response_dom_appeared_at,
            response_dom_appeared_at - wait_started,
        )
        latest = messages.last
        await latest.wait_for(state="visible", timeout=10000)

        polling_started = time.monotonic()
        logger.info("[TIMING] response_polling_start")
        last_text = ""
        last_text_changed_at = response_dom_appeared_at
        stable_reads = 0
        polling_iterations = 0
        inner_text_calls = 0
        stop_button_queries = 0
        previous_stop_state = None
        stop_generation_completed_at = None
        for _ in range(120):
            polling_iterations += 1
            extraction_started = time.monotonic()
            current_text = (await latest.inner_text()).strip()
            inner_text_calls += 1
            response_extraction_elapsed = time.monotonic() - extraction_started
            if current_text != last_text:
                text_changed_at = time.monotonic()
                logger.info(
                    "[TIMING] response_text_changed_at=%.6f elapsed=%.3fs text_length=%d",
                    text_changed_at,
                    text_changed_at - response_dom_appeared_at,
                    len(current_text),
                )
                last_text_changed_at = text_changed_at
            stop_button_queries += 1
            stop_buttons = page.locator(
                "button[aria-label*='Stop'], button[data-testid*='stop']"
            )
            matching_stop_button_count = await stop_buttons.count()
            stop_button_present = matching_stop_button_count > 0
            for stop_button_index in range(matching_stop_button_count):
                stop_button = stop_buttons.nth(stop_button_index)
                metadata = await stop_button.evaluate(
                    """element => ({
                        tag_name: element.tagName,
                        aria_label: element.getAttribute('aria-label'),
                        data_testid: element.getAttribute('data-testid'),
                        outer_html: element.outerHTML.slice(0, 500)
                    })"""
                )
                logger.info(
                    "[DOM] stop_button index=%d tag=%s aria_label=%r data_testid=%r "
                    "visible=%s enabled=%s outer_html=%r",
                    stop_button_index,
                    metadata["tag_name"],
                    metadata["aria_label"],
                    metadata["data_testid"],
                    await stop_button.is_visible(),
                    await stop_button.is_enabled(),
                    metadata["outer_html"],
                )
            stop_state_changed = previous_stop_state is not None and stop_button_present != previous_stop_state
            if stop_state_changed or previous_stop_state is None:
                stop_state_changed_at = time.monotonic()
                logger.info(
                    "[TIMING] stop_button_state_at=%.6f elapsed=%.3fs present=%s changed=%s",
                    stop_state_changed_at,
                    stop_state_changed_at - response_dom_appeared_at,
                    stop_button_present,
                    stop_state_changed,
                )
                if previous_stop_state is True and not stop_button_present:
                    stop_generation_completed_at = stop_state_changed_at
            previous_stop_state = stop_button_present
            logger.info(
                "[POLL] iteration=%d current_text_length=%d previous_text_length=%d "
                "text_changed=%s stable_reads=%d stop_button_present=%s "
                "matching_stop_button_count=%d",
                polling_iterations,
                len(current_text),
                len(last_text),
                current_text != last_text,
                stable_reads,
                stop_button_present,
                matching_stop_button_count,
            )
            if current_text and current_text == last_text and not stop_button_present:
                stable_reads += 1
                if stable_reads >= 3:
                    final_count = await messages.count()
                    response_stable_at = time.monotonic()
                    stop_to_stable = (
                        response_stable_at - stop_generation_completed_at
                        if stop_generation_completed_at is not None
                        else None
                    )
                    logger.info(
                        "[TIMING] response_stable_at=%.6f elapsed=%.3fs "
                        "last_text_change_to_stable=%.3fs stop_to_stable=%s "
                        "response_extraction=%.3fs polling_iterations=%d "
                        "inner_text_calls=%d stop_button_queries=%d final_assistant_messages=%d",
                        response_stable_at,
                        response_stable_at - response_dom_appeared_at,
                        response_stable_at - last_text_changed_at,
                        f"{stop_to_stable:.3f}s" if stop_to_stable is not None else "unavailable",
                        response_extraction_elapsed,
                        polling_iterations,
                        inner_text_calls,
                        stop_button_queries,
                        final_count,
                    )
                    logger.info("Response received")
                    return current_text
            else:
                stable_reads = 0
            last_text = current_text
            await asyncio.sleep(0.5)
        raise RuntimeError("ChatGPT response did not finish in time.")
