import asyncio
import logging
import time
from typing import Any

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from browser_manager import BrowserManager


logger = logging.getLogger(__name__)

CLAUDE_URL_PARTS = ("claude.ai", "www.claude.ai")
CLAUDE_RESPONSE_CANDIDATES = (
    "[data-testid='transcript-row'] > [role='article']",
    "[data-message-author-role='assistant']",
    "[data-testid='message']",
)
CLAUDE_TRANSIENT_CANDIDATES = "[role='status'], [aria-live], [data-testid^='tool-status']"
CLAUDE_PROMPT_SELECTORS = (
    "div[data-testid='chat-input'][contenteditable='true']"
)
CLAUDE_POLL_ITERATIONS = 120
CLAUDE_POLL_INTERVAL_SECONDS = 0.5


class ClaudeAutomation:
    """Browser automation for Claude that extracts the live answer text from the DOM."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        self.browser_manager = browser_manager

    async def ask_claude(self, prompt: str) -> str:
        ask_started = time.monotonic()
        page = None
        try:
            page = await self._find_claude_page()
            await self._ensure_logged_in(page)

            prompt_input = await self._find_prompt_input(page)
            previous_candidates = await self._get_response_candidates(page)
            previous_text_by_key = {
                str(candidate["id"]): str(candidate["text"]) if candidate.get("text") else ""
                for candidate in previous_candidates
                if candidate.get("id")
            }

            await prompt_input.fill(prompt)
            await prompt_input.press("Enter")

            return await self._read_new_response(page, previous_candidates, previous_text_by_key)
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "Claude did not expose its prompt composer in time. "
                "Check that the Claude tab is open and logged in."
            ) from error
        finally:
            logger.info("[TIMING] total=%.3fs", time.monotonic() - ask_started)

    async def _find_claude_page(self) -> Page:
        context = await self.browser_manager.get_or_start()
        for page in context.pages:
            if page.is_closed() or not any(part in page.url for part in CLAUDE_URL_PARTS):
                continue
            title = await page.title()
            if "claude" in title.lower() or "claude" in page.url.lower():
                logger.info("[BROWSER] Claude tab found url=%s title=%r", page.url, title)
                return page
        raise RuntimeError(
            "No existing Claude tab was found. Open Claude in the Chrome instance "
            "already connected through CDP, then try again."
        )

    async def _ensure_logged_in(self, page: Page) -> None:
        if "claude.ai/login" in page.url or "auth" in page.url.lower():
            raise RuntimeError("Claude requires login. Complete login in the existing Chrome tab.")
        try:
            await self._find_prompt_input(page, timeout=1500)
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "Claude does not appear to be logged in or its prompt composer is unavailable. "
                "Complete login in the existing Chrome tab and try again."
            ) from error

    async def _find_prompt_input(self, page: Page, timeout: int = 10000) -> Locator:
        locator = page.locator(CLAUDE_PROMPT_SELECTORS).first
        await locator.wait_for(state="visible", timeout=timeout)
        return locator

    async def _read_new_response(
        self,
        page: Page,
        previous_candidates: list[dict[str, Any]],
        previous_text_by_key: dict[str, str],
    ) -> str:
        last_text = ""
        stable_reads = 0

        for iteration in range(1, CLAUDE_POLL_ITERATIONS + 1):
            candidates = await self._get_response_candidates(page)
            selected_candidate = self._select_response_candidate(candidates, previous_text_by_key)
            current_text = self._clean_response_text(
                str(selected_candidate["text"]) if selected_candidate else ""
            )
            composer_state = await self._get_composer_state(page)

            logger.info(
                "[CLAUDE_RESPONSE_DETECT] iteration=%d candidate_count=%d "
                "selected_candidate=%s selected_tag=%s selected_testid=%s "
                "selected_text_length=%d generation_active=%s completion_reason=%s",
                iteration,
                len(candidates),
                selected_candidate.get("id") if selected_candidate else None,
                selected_candidate.get("attributes", {}).get("tag_name")
                if selected_candidate
                else None,
                selected_candidate.get("attributes", {}).get("data_testid")
                if selected_candidate
                else None,
                len(current_text),
                composer_state.get("generation_active", False),
                "stable_and_generation_finished"
                if current_text and stable_reads >= 2 and not composer_state.get("generation_active", False)
                else "waiting",
            )

            if current_text and current_text == last_text:
                stable_reads += 1
            else:
                stable_reads = 0
                last_text = current_text

            generation_active = composer_state.get("generation_active", False)
            if page is not None:
                await self._log_selection_diagnostics(
                    page, selected_candidate, candidates, generation_active
                )
            if current_text and not generation_active and stable_reads >= 2:
                return current_text

            await asyncio.sleep(CLAUDE_POLL_INTERVAL_SECONDS)

        raise RuntimeError("Claude did not produce a stable response in time.")

    @staticmethod
    def _select_response_candidate(
        candidates: list[dict[str, Any]], previous_text_by_key: dict[str, str]
    ) -> dict[str, Any] | None:
        changed_candidates = []
        for candidate in candidates:
            text = candidate.get("text")
            if (
                not text
                or candidate.get("is_assistant") is False
                or candidate.get("is_transient") is True
            ):
                continue
            candidate_key = str(candidate.get("id") or candidate.get("key") or "")
            previous_text = previous_text_by_key.get(candidate_key)
            if previous_text is None or str(text) != previous_text:
                changed_candidates.append(candidate)
        return changed_candidates[-1] if changed_candidates else None

    @staticmethod
    def _clean_response_text(text: str) -> str:
        cleaned = text.strip().replace("\r\n", "\n")
        for prefix in ("claude responded", "claude said"):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix) :].lstrip("\n: -")
                break
        return cleaned.strip()

    async def _log_selection_diagnostics(
        self,
        page: Page,
        selected_candidate: dict[str, Any] | None,
        all_candidates: list[dict[str, Any]],
        generation_active: bool,
    ) -> None:
        selected_attributes = selected_candidate.get("attributes", {}) if selected_candidate else {}
        diagnostics = {
            "candidate_count": len(all_candidates),
            "selected_candidate": selected_candidate.get("id") if selected_candidate else None,
            "selected_tag": selected_attributes.get("tag_name"),
            "selected_testid": selected_attributes.get("data_testid"),
            "selected_role": selected_attributes.get("role"),
            "selected_author_role": selected_attributes.get("author_role"),
            "selected_text_preview": selected_attributes.get("text_preview"),
            "selected_outer_html_head": selected_attributes.get("outer_html_head"),
            "selected_parent_chain": selected_attributes.get("parent_chain"),
            "candidate_previews": [
                {
                    "id": candidate.get("id"),
                    "testid": candidate.get("attributes", {}).get("data_testid"),
                    "text": str(candidate.get("text", ""))[:60],
                }
                for candidate in all_candidates
            ],
            "generation_active": generation_active,
            "chat_input_count": await page.locator(
                "[data-testid='chat-input']"
            ).count(),
        }
        logger.info("[SELECTION_DIAG] %s", diagnostics)

    async def _get_response_candidates(self, page: Page) -> list[dict[str, Any]]:
        selector = ", ".join((*CLAUDE_RESPONSE_CANDIDATES, CLAUDE_TRANSIENT_CANDIDATES))
        raw_candidates = await page.locator(selector).evaluate_all(
            """elements => {
                let assistantIndex = 0;
                return elements.map((element, index) => {
                const responseBody = element.querySelector(
                    ".font-claude-response-body, .progressive-markdown"
                );
                const text = (
                    responseBody?.innerText ||
                    responseBody?.textContent ||
                    ""
                ).trim();
                const testid = element.getAttribute("data-testid");
                const role = element.getAttribute("role");
                const isTransient = Boolean(
                    role === "status" ||
                    element.hasAttribute("aria-live") ||
                    (testid && testid.startsWith("tool-status"))
                );
                const isUserMessage = Boolean(
                    element.matches("[data-testid='user-message']") ||
                    element.querySelector("[data-testid='user-message']")
                );
                const isTranscriptAssistant = Boolean(
                    element.matches("[role='article']") &&
                    element.parentElement?.matches("[data-testid='transcript-row']") &&
                    !isUserMessage
                );
                const isAssistant = Boolean(
                    !isTransient &&
                    !isUserMessage &&
                    (element.getAttribute("data-message-author-role") === "assistant" ||
                        isTranscriptAssistant ||
                        testid === "message")
                );
                const messageIndex = isAssistant ? assistantIndex++ : null;
                const id = element.getAttribute("data-message-id") ||
                    element.getAttribute("id") || `candidate:${index}`;
                const parentChain = [];
                let parent = element;
                for (let depth = 0; depth < 4 && parent; depth += 1) {
                    parentChain.push({
                        tag: parent.tagName,
                        testid: parent.getAttribute("data-testid"),
                        role: parent.getAttribute("role"),
                    });
                    parent = parent.parentElement;
                }
                return {
                    id,
                    text,
                    text_length: text.length,
                    is_empty: !text,
                    is_assistant: isAssistant,
                    is_transient: isTransient,
                    attributes: {
                        tag_name: element.tagName,
                        role,
                        author_role: element.getAttribute("data-message-author-role"),
                        aria_label: element.getAttribute("aria-label"),
                        data_testid: testid,
                        text_preview: text.slice(0, 120),
                        outer_html_head: element.outerHTML.slice(0, 500),
                        parent_chain: parentChain,
                        message_index: messageIndex,
                        index,
                    },
                };
            }).map(candidate => {
                if (candidate.is_assistant && candidate.attributes.message_index !== null) {
                    candidate.id = `assistant-index:${candidate.attributes.message_index}`;
                }
                return candidate;
            });
            }"""
        )
        candidates = []
        for candidate in raw_candidates:
            if candidate.get("is_transient"):
                logger.info(
                    "[CLAUDE_RESPONSE_DETECT] rejected_transient_candidate=%s reason=status_or_live_region",
                    candidate.get("text", "")[:80],
                )
            elif candidate.get("is_assistant"):
                candidates.append(candidate)
        return candidates

    async def _get_composer_state(self, page: Page) -> dict[str, Any]:
        return await page.evaluate(
            """() => {
                const prompt = document.querySelector("div[data-testid='chat-input'][contenteditable='true']");
                const isVisible = (element) => {
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const composer = prompt?.closest('form') || prompt?.parentElement?.parentElement;
                const controls = composer ? Array.from(composer.querySelectorAll("button, input[type='submit']")) : [];
                const visibleControls = controls.filter((element) => {
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                });
                const hasStop = visibleControls.some((control) => {
                    const label = ((control.getAttribute('aria-label') || '') + ' ' + (control.getAttribute('data-testid') || '')).toLowerCase();
                    return label.includes('stop');
                });
                const sendButton = document.querySelector("button[data-testid='chat-input-send']");
                return {
                    prompt_exists: Boolean(prompt),
                    prompt_visible: isVisible(prompt),
                    visible_stop_control_count: hasStop ? 1 : 0,
                    send_button_visible: isVisible(sendButton),
                    generation_active: hasStop,
                };
            }"""
        )
