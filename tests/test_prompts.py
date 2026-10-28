from factories import make_event

from bpa_app.prompts import (
    event_qa_system,
    event_qa_user_prompt,
    extract_details_prompt,
)


def test_prompt_mentions_key_rules() -> None:
    prompt = extract_details_prompt("430", "Video Production Team")
    for term in ("rubric", "max_points", "rubric_total_points", "summary", "keywords"):
        assert term in prompt


def test_prompt_with_pdf_has_no_document_text() -> None:
    prompt = extract_details_prompt("430", "Video Production Team")
    assert "430 Video Production Team" in prompt
    assert "attached as a PDF" in prompt
    assert "<guideline>" not in prompt


def test_prompt_with_text_embeds_document() -> None:
    prompt = extract_details_prompt(
        "430", "Video Production Team", "Some {braces} text"
    )
    assert "<guideline>\nSome {braces} text\n</guideline>" in prompt


def test_event_qa_system_has_rules_and_full_guideline() -> None:
    event = make_event("430", "Video Production Team")
    system = event_qa_system(event, "## Page 1\nFee is {$10}")
    assert "430 Video Production Team" in system
    assert "<guideline>\n## Page 1\nFee is {$10}\n</guideline>" in system
    for rule in ("ONLY from the guideline", "chapter advisor", "Never make up"):
        assert rule in system


def test_event_qa_user_prompt_formats_history_and_question() -> None:
    assert event_qa_user_prompt([], "Hi?") == "Student's new question: Hi?"
    history = [
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
    ]
    assert event_qa_user_prompt(history, "Q2") == (
        "Conversation so far:\nStudent: Q1\n\nAssistant: A1\n\nStudent's new question: Q2"
    )
