import asyncio
import logging
import time
from typing import Any

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from browser_manager import BrowserManager


logger = logging.getLogger(__name__)

GEMINI_URL_PARTS = ("gemini.google.com",)
GEMINI_RESPONSE_CANDIDATES = (
    "model-response, [data-message-author-role='model'], "
    "[data-message-author-role='assistant']"
)
GEMINI_RESPONSE_FALLBACK = "[data-message-id]"
GEMINI_PROMPT_SELECTORS = (
    "rich-textarea .ql-editor[contenteditable='true'][role='textbox']"
    "[aria-label='Enter a prompt for Gemini'], "
    "[data-test-id='textarea-inner'] [contenteditable='true'][role='textbox'], "
    "textarea[aria-label*='Enter a prompt'], "
    "[contenteditable='true'][aria-label*='Enter a prompt'], "
    "rich-textarea [contenteditable='true']"
)
DIAGNOSTIC_POLL_ITERATIONS = 120
DIAGNOSTIC_POLL_INTERVAL_SECONDS = 0.5


class GeminiAutomation:
    """Browser automation for Gemini that reads the live response DOM once it appears."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        self.browser_manager = browser_manager

    async def ask_gemini(self, prompt: str) -> str:
        """Submit a prompt and return the Gemini response once the live DOM stabilizes."""
        ask_started = time.monotonic()
        logger.info("[TIMING] ask_start")
        page = None
        try:
            page = await self._find_gemini_page()
            await self._ensure_logged_in(page)

            prompt_lookup_started = time.monotonic()
            prompt_input = await self._find_prompt_input(page)
            logger.info(
                "[TIMING] find_prompt_input=%.3fs",
                time.monotonic() - prompt_lookup_started,
            )
            logger.info("[TIMING] before_prompt_insertion=%.3fs", time.monotonic() - ask_started)

            previous_candidates = await self._get_response_candidates(page)
            previous_ids = {candidate["id"] for candidate in previous_candidates if candidate["id"]}
            logger.info(
                "[RESPONSE_DETECT] existing_candidate_count=%d existing_candidate_ids=%s",
                len(previous_candidates),
                sorted(previous_ids),
            )

            fill_started = time.monotonic()
            await prompt_input.fill(prompt)
            logger.info("[TIMING] prompt_fill=%.3fs", time.monotonic() - fill_started)
            submit_started = time.monotonic()
            await prompt_input.press("Enter")
            logger.info("[TIMING] submit=%.3fs", time.monotonic() - submit_started)

            return await self._read_new_response(page, previous_candidates)
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "Gemini did not expose its prompt composer in time. "
                "Check that the existing Gemini tab is open and logged in."
            ) from error
        finally:
            logger.info("[TIMING] total=%.3fs", time.monotonic() - ask_started)

    async def _find_gemini_page(self) -> Page:
        context = await self.browser_manager.get_or_start()
        for page in context.pages:
            if page.is_closed() or not any(part in page.url for part in GEMINI_URL_PARTS):
                continue
            title = await page.title()
            if "gemini" in title.lower():
                logger.info("[BROWSER] Gemini tab found url=%s title=%r", page.url, title)
                return page
        raise RuntimeError(
            "No existing Gemini tab was found. Open Gemini in the Chrome instance "
            "already connected through CDP, then try again."
        )

    async def _ensure_logged_in(self, page: Page) -> None:
        if "accounts.google.com" in page.url or "/signin" in page.url:
            raise RuntimeError("Gemini requires login. Complete login in the existing Chrome tab.")
        try:
            await self._find_prompt_input(page, timeout=1500)
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "Gemini does not appear to be logged in or its prompt composer is unavailable. "
                "Complete login in the existing Chrome tab and try again."
            ) from error

    async def _find_prompt_input(self, page: Page, timeout: int = 10000) -> Locator:
        locator = page.locator(GEMINI_PROMPT_SELECTORS).first
        await locator.wait_for(state="visible", timeout=timeout)
        return locator

    async def _read_new_response(
        self, page: Page, previous_candidates: list[dict[str, Any]]
    ) -> str:
        logger.info("[TIMING] response_polling_start")
        previous_ids = {candidate["id"] for candidate in previous_candidates if candidate["id"]}
        previous_text_by_key = {
            str(candidate["id"]): str(candidate["text"]) if candidate.get("text") is not None else ""
            for candidate in previous_candidates
            if candidate.get("id")
        }
        last_text = ""
        stable_reads = 0

        for iteration in range(1, DIAGNOSTIC_POLL_ITERATIONS + 1):
            candidates = await self._get_response_candidates(page)
            selected_candidate = self._select_response_candidate(
                candidates,
                previous_text_by_key,
            )
            current_text = self._clean_response_text(
                str(selected_candidate["text"]) if selected_candidate else ""
            )
            composer_state = await self._get_composer_state(page)

            if selected_candidate is not None:
                logger.info(
                    "[RESPONSE_DETECT] iteration=%d candidate_count=%d selected_id=%s selected_text_length=%d "
                    "new_candidate_ids=%s composer=%s",
                    iteration,
                    len(candidates),
                    selected_candidate["id"],
                    len(current_text),
                    [candidate["id"] for candidate in candidates if candidate["id"] not in previous_ids],
                    composer_state,
                )
            else:
                logger.info(
                    "[RESPONSE_DETECT] iteration=%d candidate_count=%d selected_id=None composer=%s",
                    iteration,
                    len(candidates),
                    composer_state,
                )

            if current_text and current_text == last_text:
                stable_reads += 1
            else:
                stable_reads = 0
                last_text = current_text

            generation_active = composer_state.get("visible_stop_control_count", 0) > 0
            if current_text and not generation_active and stable_reads >= 2:
                logger.info("[POLL] response_stable iteration=%d text_length=%d", iteration, len(current_text))
                return current_text

            await asyncio.sleep(DIAGNOSTIC_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            "Gemini did not produce a stable response in time. "
            "Check the live Gemini page and inspect DOM diagnostics."
        )

    @staticmethod
    def _clean_response_text(text: str) -> str:
        cleaned = text.strip()
        cleaned = cleaned.replace("\r\n", "\n")
        if cleaned.lower().startswith("gemini said"):
            cleaned = cleaned[len("gemini said") :].lstrip("\n: -")
        return cleaned.strip()

    @staticmethod
    def _select_response_candidate(
        candidates: list[dict[str, Any]], previous_text_by_key: dict[str, str]
    ) -> dict[str, Any] | None:
        changed_candidates = []
        for candidate in candidates:
            text = candidate.get("text")
            if not text:
                continue
            candidate_key = str(candidate.get("id") or candidate.get("key") or "")
            previous_text = previous_text_by_key.get(candidate_key)
            if previous_text is None or str(text) != previous_text:
                changed_candidates.append(candidate)
        return changed_candidates[-1] if changed_candidates else None

    async def _get_response_candidates(self, page: Page) -> list[dict[str, Any]]:
        candidates = page.locator(GEMINI_RESPONSE_CANDIDATES)
        if await candidates.count() == 0:
            candidates = page.locator(GEMINI_RESPONSE_FALLBACK)
        return await candidates.evaluate_all(
            """elements => elements.map((element, index) => {
                const text = (element.innerText || element.textContent || "").trim();
                const id = element.getAttribute("data-message-id") || element.getAttribute("id") || `index:${index}`;
                return {
                    id,
                    text,
                    text_length: text.length,
                    is_empty: text.length === 0,
                    attributes: {
                        tag_name: element.tagName,
                        data_message_id: element.getAttribute("data-message-id"),
                        data_message_author_role: element.getAttribute("data-message-author-role"),
                        data_testid: element.getAttribute("data-testid"),
                        role: element.getAttribute("role"),
                        aria_label: element.getAttribute("aria-label"),
                        index,
                    },
                };
            })"""
        )

    async def _get_composer_state(self, page: Page) -> dict[str, Any]:
        return await page.evaluate(
            """() => {
                const prompt = document.querySelector(
                    "rich-textarea .ql-editor[contenteditable='true'][role='textbox']" +
                    "[aria-label='Enter a prompt for Gemini'], " +
                    "[data-test-id='textarea-inner'] [contenteditable='true'][role='textbox'], " +
                    "textarea[aria-label*='Enter a prompt'], " +
                    "[contenteditable='true'][aria-label*='Enter a prompt'], " +
                    "rich-textarea [contenteditable='true']"
                );
                const isVisible = (element) => {
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== "none" && style.visibility !== "hidden" &&
                        rect.width > 0 && rect.height > 0;
                };
                const isEnabled = (element) => !element.disabled &&
                    element.getAttribute("aria-disabled") !== "true";
                const composer = prompt?.closest("form") || prompt?.parentElement?.parentElement;
                const controls = composer
                    ? Array.from(composer.querySelectorAll("button, input[type='submit']"))
                    : [];
                const visibleControls = controls
                    .filter((element) => isVisible(element) && isEnabled(element))
                    .map((element) => ({
                        aria_label: element.getAttribute("aria-label"),
                        data_testid: element.getAttribute("data-testid"),
                    }));
                const isStopControl = (control) => {
                    const ariaLabel = (control.aria_label || "").toLowerCase();
                    const testId = (control.data_testid || "").toLowerCase();
                    return ariaLabel.includes("stop") || testId.includes("stop");
                };
                return {
                    prompt_exists: Boolean(prompt),
                    prompt_visible: isVisible(prompt),
                    prompt_empty: prompt
                        ? (prompt.innerText || prompt.textContent || "").trim().length === 0
                        : null,
                    visible_stop_control_count: visibleControls.filter(isStopControl).length,
                    visible_controls: visibleControls,
                };
            }"""
        )
