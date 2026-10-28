from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bpa_app import llm, ratelimit
from bpa_app.models import SearchFilters, SearchHit, SearchResult

BROWSE_PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "browse.py")


def _count(at: AppTest) -> str:
    return next(m.value for m in at.markdown if m.value.endswith(" events"))


def test_browse_filters_and_clears() -> None:
    at = AppTest.from_file(BROWSE_PAGE, default_timeout=30).run()
    assert not at.exception
    total = _count(at)
    assert total.startswith("**113** of 113")

    at.multiselect(key="f_formats").set_value(["Virtual"]).run()
    assert _count(at).startswith("**16** of 113")

    next(b for b in at.button if b.label == "Clear filters").click().run()
    assert _count(at) == total
    assert at.multiselect(key="f_formats").value == []


def test_each_event_card_has_a_details_button() -> None:
    at = AppTest.from_file(BROWSE_PAGE, default_timeout=30).run()
    assert len([b for b in at.button if b.label == "Details"]) == 113


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def _details_count(at: AppTest) -> int:
    return len([b for b in at.button if b.label == "Details"])


def _captions(at: AppTest) -> list[str]:
    return [c.value for c in at.caption]


def _fake_result() -> SearchResult:
    return SearchResult(
        filters=SearchFilters(
            formats=["Virtual"], participation=["Team"], divisions=["MS"]
        ),
        results=[SearchHit(id="V02", reason="Team video project for middle school")],
        interpretation="Showing virtual team events for middle school.",
    )


def _ask(at: AppTest, query: str) -> AppTest:
    at.text_input(key="nl_query").set_value(query).run()
    next(b for b in at.button if b.label == "✨ Ask AI").click().run()
    return at


def test_typing_shows_keyword_results_without_calling_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a, **_k):
        raise AssertionError("AI must not run before Ask AI")

    monkeypatch.setattr(llm, "nl_search", boom)
    at = AppTest.from_file(BROWSE_PAGE, default_timeout=30).run()
    at.text_input(key="nl_query").set_value("accounting").run()
    assert not at.exception
    assert any(m.value.endswith("keyword matches") for m in at.markdown)
    assert 0 < _details_count(at) < 113


def test_ai_search_applies_filters_and_shows_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "nl_search", lambda *_a, **_k: _fake_result())
    at = _ask(
        AppTest.from_file(BROWSE_PAGE, default_timeout=30).run(),
        "Virtual team events for MS?",
    )

    assert not at.exception
    assert (
        next(i.value for i in at.info)
        == "Showing virtual team events for middle school."
    )
    assert at.multiselect(key="f_formats").value == ["Virtual"]
    assert at.multiselect(key="f_participation").value == ["Team"]
    assert at.multiselect(key="f_divisions").value == ["MS"]
    assert _details_count(at) == 1
    assert any(
        m.value == "💡 *Team video project for middle school*" for m in at.markdown
    )
    assert any("AI-generated" in c for c in _captions(at))


def test_repeated_query_is_served_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake(query, _events):
        calls.append(query)
        return _fake_result()

    monkeypatch.setattr(llm, "nl_search", fake)
    at = _ask(
        AppTest.from_file(BROWSE_PAGE, default_timeout=30).run(),
        "virtual team events for ms",
    )
    # Same question with different case/punctuation, from a new session.
    _ask(
        AppTest.from_file(BROWSE_PAGE, default_timeout=30).run(),
        "Virtual team events for MS?",
    )
    assert calls == ["virtual team events for ms"]
    assert len(at.session_state["ai_call_times"]) == 1


def test_ai_failure_falls_back_to_keyword_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_a, **_k):
        raise llm.LLMError("The AI service is busy right now.")

    monkeypatch.setattr(llm, "nl_search", fail)
    at = _ask(AppTest.from_file(BROWSE_PAGE, default_timeout=30).run(), "accounting")

    assert not at.exception
    assert any(
        "busy right now. Showing keyword results instead." in c for c in _captions(at)
    )
    assert 0 < _details_count(at) < 113


def test_rate_limit_falls_back_to_keyword_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ratelimit,
        "check_and_count",
        lambda _kind: (False, "You've reached the hourly limit for AI search."),
    )
    monkeypatch.setattr(
        llm, "nl_search", lambda *_a, **_k: pytest.fail("must not call AI")
    )
    at = _ask(AppTest.from_file(BROWSE_PAGE, default_timeout=30).run(), "accounting")

    assert not at.exception
    assert any("hourly limit" in c and "keyword results" in c for c in _captions(at))


def test_example_chip_runs_ai_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "nl_search", lambda *_a, **_k: _fake_result())
    at = AppTest.from_file(BROWSE_PAGE, default_timeout=30).run()
    at.button(key="chip_0").click().run()
    assert (
        at.text_input(key="nl_query").value == "virtual team events for middle school"
    )
    assert next(i.value for i in at.info).startswith("Showing virtual team")


def test_clear_filters_also_clears_ai_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "nl_search", lambda *_a, **_k: _fake_result())
    at = _ask(
        AppTest.from_file(BROWSE_PAGE, default_timeout=30).run(),
        "virtual team events for ms",
    )
    next(b for b in at.button if b.label == "Clear filters").click().run()
    assert at.text_input(key="nl_query").value == ""
    assert at.multiselect(key="f_formats").value == []
    assert _details_count(at) == 113
