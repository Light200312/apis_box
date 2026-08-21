from gemini_automation import GeminiAutomation


def test_select_response_candidate_returns_latest_changed_message():
    candidates = [
        {"key": "first", "text": "initial"},
        {"key": "second", "text": "answer part 1"},
        {"key": "third", "text": "answer part 2"},
    ]

    selected = GeminiAutomation._select_response_candidate(
        candidates,
        {"first": "initial"},
    )

    assert selected is not None
    assert selected["key"] == "third"


def test_select_response_candidate_returns_none_when_no_new_text():
    candidates = [
        {"key": "first", "text": "text"},
    ]

    selected = GeminiAutomation._select_response_candidate(
        candidates,
        {"first": "text"},
    )

    assert selected is None


def test_clean_response_text_removes_gemini_label_prefix():
    cleaned = GeminiAutomation._clean_response_text("Gemini said\n8")

    assert cleaned == "8"
