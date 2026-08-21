import asyncio
import logging
import time
from typing import Any

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from browser_manager import BrowserManager


logger = logging.getLogger(__name__)

DEEPSEEK_URL_PARTS = ("deepseek.com", "chat.deepseek.com")
DEEPSEEK_PROMPT_SELECTORS = (
    "textarea[placeholder='Message DeepSeek']",
    "textarea[name='search'][placeholder*='DeepSeek']",
)
DEEPSEEK_RESPONSE_SELECTORS = (
    "[data-message-author-role='assistant']",
    "[data-testid='assistant-message']",
    ".ds-markdown",
    "[class*='markdown'][class*='message']",
)
DEEPSEEK_POLL_ITERATIONS = 120
DEEPSEEK_POLL_INTERVAL_SECONDS = 0.5


class DeepSeekAutomation:
    """Automate DeepSeek through the existing Chrome CDP session."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        self.browser_manager = browser_manager

    async def ask_deepseek(self, prompt: str) -> str:
        started = time.monotonic()
        try:
            page = await self._find_deepseek_page()
            prompt_input = await self._find_prompt_input(page)
            previous_candidates = await self._get_response_candidates(page)
            previous_text_by_id = {
                str(candidate["id"]): str(candidate.get("text") or "")
                for candidate in previous_candidates
                if candidate.get("id")
            }

            await prompt_input.fill(prompt)
            await prompt_input.press("Enter")
            return await self._read_new_response(page, previous_text_by_id)
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "DeepSeek did not expose its prompt composer in time. "
                "Check that the DeepSeek tab is open and logged in."
            ) from error
        finally:
            logger.info("[DEEPSEEK_TIMING] total=%.3fs", time.monotonic() - started)

    async def _find_deepseek_page(self) -> Page:
        context = await self.browser_manager.get_or_start()
        for page in context.pages:
            if page.is_closed() or not any(part in page.url for part in DEEPSEEK_URL_PARTS):
                continue
            title = await page.title()
            if "deepseek" not in page.url.lower() and "deepseek" not in title.lower():
                continue
            prompt = page.locator(", ".join(DEEPSEEK_PROMPT_SELECTORS)).first
            if await prompt.count() > 0 and await prompt.is_visible():
                logger.info("[BROWSER] DeepSeek tab found url=%s title=%r", page.url, title)
                return page
        raise RuntimeError(
            "No logged-in DeepSeek chat tab was found. Open DeepSeek chat in the Chrome "
            "instance already connected through CDP, then try again."
        )

    async def _find_prompt_input(self, page: Page, timeout: int = 10000) -> Locator:
        prompt_input = page.locator(", ".join(DEEPSEEK_PROMPT_SELECTORS)).first
        await prompt_input.wait_for(state="visible", timeout=timeout)
        return prompt_input

    async def _read_new_response(
        self, page: Page, previous_text_by_id: dict[str, str]
    ) -> str:
        last_text = ""
        stable_reads = 0
        for iteration in range(1, DEEPSEEK_POLL_ITERATIONS + 1):
            candidates = await self._get_response_candidates(page)
            selected = self._select_response_candidate(candidates, previous_text_by_id)
            text = self._clean_response_text(str(selected.get("text") or "") if selected else "")
            state = await self._get_composer_state(page)
            generation_active = state.get("generation_active", False)

            if text and text == last_text:
                stable_reads += 1
            else:
                stable_reads = 0
                last_text = text

            logger.info(
                "[DEEPSEEK_RESPONSE_DETECT] iteration=%d candidate_count=%d selected_id=%s "
                "text_length=%d generation_active=%s",
                iteration,
                len(candidates),
                selected.get("id") if selected else None,
                len(text),
                generation_active,
            )
            if text and not generation_active and stable_reads >= 2:
                return text
            await asyncio.sleep(DEEPSEEK_POLL_INTERVAL_SECONDS)

        raise RuntimeError("DeepSeek did not produce a stable response in time.")

    @staticmethod
    def _select_response_candidate(
        candidates: list[dict[str, Any]], previous_text_by_id: dict[str, str]
    ) -> dict[str, Any] | None:
        changed = []
        for candidate in candidates:
            if not candidate.get("is_assistant") or not candidate.get("text"):
                continue
            candidate_id = str(candidate.get("id") or "")
            if candidate_id not in previous_text_by_id or str(candidate["text"]) != previous_text_by_id[candidate_id]:
                changed.append(candidate)
        return changed[-1] if changed else None

    @staticmethod
    def _clean_response_text(text: str) -> str:
        return text.strip().replace("\r\n", "\n").strip()

    async def _get_response_candidates(self, page: Page) -> list[dict[str, Any]]:
        return await page.locator(", ".join(DEEPSEEK_RESPONSE_SELECTORS)).evaluate_all(
            """elements => elements.map((element, index) => {
                const text = (element.innerText || element.textContent || '').trim();
                const role = element.getAttribute('data-message-author-role');
                const testid = element.getAttribute('data-testid');
                const isMarkdown = element.matches('.ds-markdown, [class*="markdown"][class*="message"]');
                return {
                    id: element.getAttribute('data-message-id') || element.id || `index:${index}`,
                    text,
                    is_assistant: role === 'assistant' || testid === 'assistant-message' || isMarkdown,
                    attributes: { tag_name: element.tagName, role, testid },
                };
            })"""
        )

    async def _get_composer_state(self, page: Page) -> dict[str, Any]:
        return await page.evaluate(
            """() => {
                const prompt = document.querySelector("textarea[placeholder='Message DeepSeek']");
                const visible = element => {
                    if (!element) return false;
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' &&
                        rect.width > 0 && rect.height > 0;
                };
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).filter(visible);
                const generationActive = buttons.some(button => {
                    const label = ((button.getAttribute('aria-label') || '') + ' ' +
                        (button.getAttribute('data-testid') || '') + ' ' +
                        (button.textContent || '')).toLowerCase();
                    return label.includes('stop') || label.includes('cancel') || label.includes('generating');
                });
                return {
                    prompt_exists: Boolean(prompt),
                    prompt_visible: visible(prompt),
                    prompt_count: document.querySelectorAll("textarea[placeholder='Message DeepSeek']").length,
                    generation_active: generationActive,
                };
            }"""
        )
