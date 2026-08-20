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
            previous_candidates = await self._get_assistant_response_candidates(
                assistant_messages
            )
            logger.info("[TIMING] existing_assistant_messages=%d", message_count)

            prompt_fill_started = time.monotonic()
            await prompt_input.fill(prompt)
            logger.info("[TIMING] prompt_fill=%.3fs", time.monotonic() - prompt_fill_started)
            submit_started = time.monotonic()
            await prompt_input.press("Enter")
            logger.info("[TIMING] submit=%.3fs", time.monotonic() - submit_started)
            await set_status("Waiting for response...")
            return await self._read_new_response(page, previous_candidates)
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

    async def _read_new_response(
        self, page: Page, previous_candidates: list[dict[str, object]]
    ) -> str:
        messages = page.locator(ASSISTANT_MESSAGES)
        wait_started = time.monotonic()
        polling_started = time.monotonic()
        logger.info("[TIMING] response_polling_start")
        previous_text_by_key = {
            str(candidate["key"]): str(candidate["text"])
            for candidate in previous_candidates
        }
        last_text = ""
        last_text_changed_at = polling_started
        response_dom_appeared_at = None
        stable_reads = 0
        polling_iterations = 0
        inner_text_calls = 0
        last_selected_key = None
        for _ in range(120):
            polling_iterations += 1
            extraction_started = time.monotonic()
            candidates = await self._get_assistant_response_candidates(messages)
            selected_candidate = self._select_response_candidate(
                candidates, previous_text_by_key
            )
            current_text = (
                str(selected_candidate["text"]) if selected_candidate is not None else ""
            )
            inner_text_calls += 1
            response_extraction_elapsed = time.monotonic() - extraction_started
            if selected_candidate is not None:
                selected_key = str(selected_candidate["key"])
                if selected_key != last_selected_key:
                    logger.info(
                        "[RESPONSE_DETECT] candidate_count=%d candidate_ids=%s "
                        "content_lengths=%s selected_message_id=%s selected_text_length=%d",
                        len(candidates),
                        [candidate["message_id"] for candidate in candidates],
                        [len(str(candidate["text"])) for candidate in candidates],
                        selected_candidate["message_id"],
                        len(current_text),
                    )
                    last_selected_key = selected_key
                if response_dom_appeared_at is None:
                    response_dom_appeared_at = time.monotonic()
                    logger.info(
                        "[TIMING] response_dom_appeared_at=%.6f wait_new_message=%.3fs",
                        response_dom_appeared_at,
                        response_dom_appeared_at - wait_started,
                    )
            elif polling_iterations == 1 or polling_iterations % 10 == 0:
                logger.info(
                    "[RESPONSE_DETECT] candidate_count=%d candidate_ids=%s "
                    "content_lengths=%s selected_message_id=None selected_text_length=0",
                    len(candidates),
                    [candidate["message_id"] for candidate in candidates],
                    [len(str(candidate["text"])) for candidate in candidates],
                )
            if current_text != last_text:
                text_changed_at = time.monotonic()
                logger.info(
                    "[TIMING] response_text_changed_at=%.6f elapsed=%.3fs text_length=%d",
                    text_changed_at,
                    text_changed_at - response_dom_appeared_at,
                    len(current_text),
                )
                last_text_changed_at = text_changed_at
            logger.info(
                "[POLL] iteration=%d current_text_length=%d previous_text_length=%d "
                "text_changed=%s stable_reads=%d",
                polling_iterations,
                len(current_text),
                len(last_text),
                current_text != last_text,
                stable_reads,
            )
            if current_text and current_text == last_text:
                stable_reads += 1
                if stable_reads >= 3:
                    final_count = await messages.count()
                    response_stable_at = time.monotonic()
                    logger.info(
                        "[TIMING] response_stable_at=%.6f elapsed=%.3fs "
                        "last_text_change_to_stable=%.3fs "
                        "response_extraction=%.3fs polling_iterations=%d "
                        "inner_text_calls=%d final_assistant_messages=%d",
                        response_stable_at,
                        response_stable_at - (response_dom_appeared_at or polling_started),
                        response_stable_at - last_text_changed_at,
                        response_extraction_elapsed,
                        polling_iterations,
                        inner_text_calls,
                        final_count,
                    )
                    logger.info(
                        "[POLL] response_stable iteration=%d stable_reads=%d text_length=%d",
                        polling_iterations,
                        stable_reads,
                        len(current_text),
                    )
                    logger.info("Response received")
                    return current_text
            else:
                stable_reads = 0
            last_text = current_text
            await asyncio.sleep(0.5)
        raise RuntimeError("ChatGPT response did not finish in time.")

    async def _get_assistant_response_candidates(self, messages) -> list[dict[str, object]]:
        """Extract content only from individual assistant-message containers."""
        candidates = await messages.evaluate_all(
            """elements => elements.map((element, index) => {
                const textOf = (node) => (node?.innerText || "").trim();
                const copyTargetText = textOf(
                    element.querySelector("[data-dil-widget-copy-target]")
                );
                const markdownText = Array.from(element.querySelectorAll(".markdown"))
                    .map(textOf)
                    .filter(Boolean)
                    .join("\\n");
                const text = copyTargetText || markdownText || textOf(element);
                const messageId = element.getAttribute("data-message-id");
                return { index, message_id: messageId, text };
            })"""
        )
        for candidate in candidates:
            candidate["key"] = candidate["message_id"] or f"index:{candidate['index']}"
        return candidates

    @staticmethod
    def _select_response_candidate(
        candidates: list[dict[str, object]], previous_text_by_key: dict[str, str]
    ) -> dict[str, object] | None:
        changed_candidates = [
            candidate
            for candidate in candidates
            if candidate["text"]
            and str(candidate["text"]) != previous_text_by_key.get(str(candidate["key"]))
        ]
        return changed_candidates[-1] if changed_candidates else None
