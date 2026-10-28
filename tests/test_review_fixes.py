from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bpa_app import llm
from bpa_app.data import get_event
from bpa_app.models import CriterionScore, Evaluation
from bpa_app.ui import COMPARE_FIELDS, badges

PAGES = Path(__file__).resolve().parent.parent / "pages"
THINKING = "Looking through the guidelines…"


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def _page(name: str, event_id: str | None = None) -> AppTest:
    at = AppTest.from_file(str(PAGES / f"{name}.py"), default_timeout=30)
    if event_id:
        at.query_params["event"] = event_id
    return at


def _markdown(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def _captions(at: AppTest) -> list[str]:
    return [c.value for c in at.caption]


# --- consistent badges -------------------------------------------------------


@pytest.mark.parametrize(
    ("page", "event_id"),
    [("event", "430"), ("evaluate", "430"), ("study", "355")],
)
def test_event_pages_show_the_same_badges(page: str, event_id: str) -> None:
    at = _page(page, event_id).run()
    assert not at.exception
    assert badges(get_event(event_id)) in _markdown(at)


def test_browse_cards_use_the_same_badges() -> None:
    at = _page("browse").run()
    assert badges(get_event("430")) in _markdown(at)


def test_badges_show_flags_only_when_true() -> None:
    text = badges(get_event("730"))  # a certification event
    assert "Certification" in text and "Presubmit" in text
    assert "Certification" not in badges(get_event("430"))


# --- chat thinking indicator -------------------------------------------------


def test_thinking_note_is_cleared_after_a_successful_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "stream_text", lambda *_a, **_k: iter(["An ", "answer."]))
    at = _page("event", "430").run()
    at.chat_input[0].set_value("How is this event scored?").run()
    assert not at.exception
    assert THINKING not in _captions(at)
    assert at.session_state["chats"]["430"][1]["content"] == "An answer."


def test_thinking_note_is_cleared_after_an_ai_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_a, **_k):
        raise llm.LLMError("The AI service is busy right now.")
        yield  # makes this a generator

    monkeypatch.setattr(llm, "stream_text", fail)
    at = _page("event", "430").run()
    at.chat_input[0].set_value("How is this event scored?").run()
    assert any("busy right now" in e.value for e in at.error)
    assert THINKING not in _captions(at)


def test_unconfigured_ai_is_reported_and_clears_the_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_key(*_a, **_k):
        raise RuntimeError("GEMINI_API_KEY not found")
        yield  # makes this a generator

    monkeypatch.setattr(llm, "stream_text", no_key)
    at = _page("event", "430").run()
    at.chat_input[0].set_value("How is this event scored?").run()
    assert not at.exception
    assert any("not configured" in e.value for e in at.error)
    assert THINKING not in _captions(at)
    assert not any("GEMINI_API_KEY" in e.value for e in at.error)  # no internals leaked


# --- AI disclaimer on evaluation results ------------------------------------


def test_evaluation_results_carry_both_disclaimers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = Evaluation(
        criteria=[
            CriterionScore(
                criterion="Creativity & Originality",
                max_points=25,
                estimated_points=10,
                evidence="e",
                suggestions="s",
            )
        ],
        missing_requirements=[],
        strengths=[],
        top_3_improvements=[],
        estimated_total=10,
        max_total=25,
        cannot_assess=[],
    )
    monkeypatch.setattr(llm, "evaluate_submission", lambda *_a, **_k: result)
    at = _page("evaluate", "430").run()
    at.text_area[0].set_value("a draft").run()
    next(b for b in at.button if b.label == "Evaluate my draft").click().run()
    assert any("Practice estimate only" in w.value for w in at.warning)
    assert any("AI-generated – may contain errors" in c for c in _captions(at))


# --- mobile layout: Compare tags every cell with its event -------------------


def test_compare_tags_every_value_with_its_event_for_stacked_phone_layouts() -> None:
    at = _page("compare").run()
    next(b for b in at.button if b.label == "Video").click().run()
    assert not at.exception

    markdown = _markdown(at)
    tags = [m for m in markdown if 'class="cmp-tag"' in m]
    assert len(tags) == len(COMPARE_FIELDS) * 2  # one per field per event (430, 950)
    assert tags[:2] == [
        '<span class="cmp-tag">Event 430</span>',
        '<span class="cmp-tag">Event 950</span>',
    ]


def test_compare_tags_are_hidden_on_wide_screens_and_shown_on_phones() -> None:
    at = _page("compare").run()
    next(b for b in at.button if b.label == "Video").click().run()
    css = next(m for m in _markdown(at) if m.lstrip().startswith("<style>"))
    assert ".cmp-tag { display: none;" in css
    assert "@media (max-width: 640px) { .cmp-tag { display: inline-block; } }" in css


def test_compare_page_without_a_selection_has_no_tags_or_css() -> None:
    at = _page("compare").run()
    assert not any("cmp-tag" in m for m in _markdown(at))
