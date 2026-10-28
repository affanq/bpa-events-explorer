from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bpa_app import llm, ratelimit
from bpa_app.data import load_events

EVENT_PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "event.py")


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def _page(event_id: str = "430") -> AppTest:
    at = AppTest.from_file(EVENT_PAGE, default_timeout=30)
    at.query_params["event"] = event_id
    return at


def _find(predicate) -> str:
    return next(e.id for e in load_events() if predicate(e))


def _chat_texts(at: AppTest) -> list[str]:
    return [m.markdown[0].value for m in at.chat_message]


class FakeStream:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        chunks=("It is ", "scored out of 280. $10 fee"),
    ):
        self.calls: list[dict] = []
        self.chunks = chunks

        def fake(prompt, *, system=None, model=None, temperature=0.2):
            self.calls.append({"prompt": prompt, "system": system, "model": model})
            yield from self.chunks

        monkeypatch.setattr(llm, "stream_text", fake)


def test_header_and_tabs_render_for_a_judged_event() -> None:
    at = _page().run()
    assert not at.exception
    assert at.title[0].value == "Video Production Team"
    assert [t.label for t in at.tabs] == [
        "Overview",
        "Requirements & Checklist",
        "Rubric",
        "Ask a question",
    ]
    assert any(b.label == "⬅️ Back to browse" for b in at.button)
    assert len(at.dataframe) == 1  # the rubric table
    assert len(at.checkbox) > 0


def test_testing_event_without_rubric_lists_competencies() -> None:
    event_id = _find(
        lambda e: e.event_type == ["Testing"] and e.details and not e.details.rubric
    )
    at = _page(event_id).run()
    assert not at.exception
    assert any("testing event" in i.value for i in at.info)
    assert len(at.dataframe) == 0


def test_event_without_details_or_text_degrades_gracefully() -> None:
    event_id = _find(lambda e: e.details is None and not e.has_text)
    at = _page(event_id).run()
    assert not at.exception
    assert any("hasn't been extracted" in i.value for i in at.info)
    assert any("isn't available yet" in i.value for i in at.info)
    assert not at.chat_input


def test_picker_is_used_when_no_event_in_url() -> None:
    at = AppTest.from_file(EVENT_PAGE, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Event details"
    at.selectbox[0].select("430 – Video Production Team").run()
    assert not at.exception
    assert at.query_params["event"] == "430"
    assert at.title[0].value == "Video Production Team"


def test_unknown_event_id_warns_and_shows_picker() -> None:
    at = _page("nope").run()
    assert any("nope" in w.value for w in at.warning)
    assert len(at.selectbox) == 1


def test_checklist_ticks_are_kept_in_session() -> None:
    at = _page().run()
    at.checkbox[0].check().run()
    assert at.checkbox[0].value is True
    done = at.session_state["checklist"]["430"]
    assert list(done.values()).count(True) == 1
    assert any("1 of" in c.value for c in at.caption)

    # Leaving the page drops widget state; only the session dict survives.
    returning = _page()
    returning.session_state["checklist"] = at.session_state["checklist"]
    returning.run()
    assert returning.checkbox[0].value is True
    assert returning.checkbox[1].value is False


def test_chat_streams_answer_with_guideline_and_fast_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = FakeStream(monkeypatch)
    at = _page().run()
    at.chat_input[0].set_value("How is this event scored?").run()

    assert not at.exception
    assert _chat_texts(at) == [
        "How is this event scored?",
        "It is scored out of 280. \\$10 fee",
    ]
    call = stream.calls[0]
    assert call["model"] == llm.config.MODEL_FAST
    assert "## Page 1" in call["system"] and "Video Production Team" in call["system"]
    assert call["prompt"].endswith("Student's new question: How is this event scored?")
    stored = at.session_state["chats"]["430"]
    assert stored[1] == {
        "role": "assistant",
        "content": "It is scored out of 280. $10 fee",
    }
    assert any("AI-generated" in c.value for c in at.caption)


def test_suggested_question_and_clear_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = FakeStream(monkeypatch)
    at = _page().run()
    next(
        b for b in at.button if b.label == "How long is the presentation?"
    ).click().run()
    assert stream.calls[0]["prompt"].endswith("How long is the presentation?")
    assert len(at.session_state["chats"]["430"]) == 2

    at.run()  # the Clear chat button appears once there is history
    next(b for b in at.button if b.label == "Clear chat").click().run()
    assert at.session_state["chats"]["430"] == []
    assert _chat_texts(at) == []


def test_only_last_six_messages_are_sent_back(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = FakeStream(monkeypatch)
    old = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"}
        for i in range(10)
    ]
    at = _page()
    at.session_state["chats"] = {"430": old}
    at.run()
    at.chat_input[0].set_value("And penalties?").run()

    prompt = stream.calls[0]["prompt"]
    assert "message 3" not in prompt and "message 4" in prompt and "message 9" in prompt
    assert "Student: message 4" in prompt and "Assistant: message 9" in prompt
    assert len(at.session_state["chats"]["430"]) == 12


def test_ai_failure_shows_error_and_keeps_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_a, **_k):
        raise llm.LLMError("The AI service is busy right now.")
        yield  # makes this a generator

    monkeypatch.setattr(llm, "stream_text", fail)
    at = _page().run()
    at.chat_input[0].set_value("How is this event scored?").run()

    assert not at.exception
    assert any("busy right now" in e.value for e in at.error)
    assert at.session_state["chats"]["430"] == []


def test_rate_limit_blocks_the_ai_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ratelimit,
        "check_and_count",
        lambda kind: (False, f"Hourly limit for AI {kind}."),
    )
    monkeypatch.setattr(
        llm, "stream_text", lambda *_a, **_k: pytest.fail("must not call AI")
    )
    at = _page().run()
    at.chat_input[0].set_value("How is this event scored?").run()

    assert not at.exception
    assert any(w.value == "Hourly limit for AI chat." for w in at.warning)
    assert at.session_state["chats"]["430"] == []
