from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bpa_app import llm, ratelimit
from bpa_app.data import load_events
from bpa_app.models import SearchFilters, SearchHit, SearchResult

BROWSE_PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "browse.py")
ALL_IDS = [e.id for e in load_events()]


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def _page() -> AppTest:
    return AppTest.from_file(BROWSE_PAGE, default_timeout=30).run()


def _result(n: int = 8) -> SearchResult:
    return SearchResult(
        filters=SearchFilters(formats=["Virtual"]),
        results=[SearchHit(id=i, reason=f"Reason for {i}") for i in ALL_IDS[:n]],
        interpretation="Showing the best fits for you.",
    )


class FakeSearch:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, result: SearchResult | None = None
    ):
        self.queries: list[str] = []
        self.result = result or _result()

        def fake(query, _events):
            self.queries.append(query)
            return self.result

        monkeypatch.setattr(llm, "nl_search", fake)


def _answer(
    at: AppTest,
    division: str | None = "HS",
    team: str = "Solo",
    preference: str = "A speech",
    interests=("speaking",),
    where: str = "In person",
) -> AppTest:
    if division:
        at.radio(key="hm_division").set_value(division)
    at.radio(key="hm_team").set_value(team)
    at.radio(key="hm_preference").set_value(preference)
    at.multiselect(key="hm_interests").set_value(list(interests))
    at.radio(key="hm_where").set_value(where)
    return at


def _submit(at: AppTest) -> AppTest:
    next(b for b in at.button if b.label == "Find my top 5").click().run()
    return at


def _help_cards(at: AppTest) -> list[str]:
    return [b.key for b in at.button if b.key and b.key.startswith("help_details_")]


def _texts(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def test_expander_has_the_five_questions() -> None:
    at = _page()
    assert not at.exception
    assert [e.label for e in at.expander] == ["🧭 Help me choose"]
    assert [r.label for r in at.radio] == [
        "1. Which division are you in?",
        "2. Do you want to compete solo or on a team?",
        "3. What would you rather do?",
        "5. Is in-person or virtual OK?",
    ]
    assert at.multiselect(key="hm_interests").label == "4. What are you interested in?"
    assert at.radio(key="hm_preference").options == [
        "A test",
        "A project",
        "A presentation",
        "A speech",
        "No preference",
    ]


def test_interest_options_mix_keywords_and_subjects() -> None:
    options = _page().multiselect(key="hm_interests").options
    assert options[:6] == [
        "coding",
        "design",
        "video",
        "finance",
        "healthcare",
        "speaking",
    ]
    assert "Digital Technology" in options
    assert "Virtual" not in options and "Middle School" not in options


def test_answers_become_a_query_and_show_the_top_five_with_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSearch(monkeypatch)
    at = _submit(_answer(_page()))

    assert not at.exception
    assert fake.queries == [
        (
            "individual events for high school students, that involve public speaking, "
            "about speaking, in-person only"
        )
    ]
    assert _help_cards(at) == [f"help_details_{i}" for i in ALL_IDS[:5]]  # top 5 of 8
    texts = _texts(at)
    assert "**Your top 5**" in texts
    assert f"💡 *Reason for {ALL_IDS[0]}*" in texts
    assert f"💡 *Reason for {ALL_IDS[5]}*" not in texts
    assert any(i.value == "Showing the best fits for you." for i in at.info)
    assert any("AI-generated" in c.value for c in at.caption)


def test_help_results_do_not_change_the_main_grid_or_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSearch(monkeypatch)
    at = _submit(_answer(_page()))
    assert (
        at.multiselect(key="f_formats").value == []
    )  # the AI's filters are not applied
    main = [
        b for b in at.button if b.label == "Details" and not b.key.startswith("help_")
    ]
    assert len(main) == 113
    # The same events appear in both places without key clashes.
    assert ALL_IDS[0] in {k.removeprefix("help_details_") for k in _help_cards(at)}


def test_unanswered_division_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSearch(monkeypatch)
    _submit(_answer(_page(), division=None, interests=()))
    assert fake.queries == [
        "individual events, that involve public speaking, in-person only"
    ]


def test_no_answers_asks_for_at_least_one(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSearch(monkeypatch)
    at = _submit(_page())
    assert any("at least one question" in w.value for w in at.warning)
    assert fake.queries == [] and _help_cards(at) == []


def test_same_answers_are_served_from_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSearch(monkeypatch)
    at = _submit(_answer(_page()))
    _submit(at)
    assert len(fake.queries) == 1
    assert len(at.session_state["ai_call_times"]) == 1


def test_results_survive_other_interactions(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSearch(monkeypatch)
    at = _submit(_answer(_page()))
    at.multiselect(key="f_formats").set_value(["Virtual"]).run()
    assert len(_help_cards(at)) == 5


def test_ai_failure_falls_back_to_matching_the_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_a, **_k):
        raise llm.LLMError("The AI service is busy right now.")

    monkeypatch.setattr(llm, "nl_search", fail)
    at = _submit(
        _answer(
            _page(),
            division="HS",
            team="Team",
            preference="A project",
            interests=("video",),
            where="Virtual",
        )
    )

    assert not at.exception
    assert any(
        "busy right now. Showing matches from your answers instead." in c.value
        for c in at.caption
    )
    shown = [k.removeprefix("help_details_") for k in _help_cards(at)]
    by_id = {e.id: e for e in load_events()}
    assert shown and len(shown) <= 5
    assert all(
        by_id[i].format == "Virtual"
        and by_id[i].participation == "Team"
        and "HS" in by_id[i].divisions
        and "Judged" in by_id[i].event_type
        for i in shown
    )


def test_rate_limit_falls_back_without_calling_the_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ratelimit,
        "check_and_count",
        lambda kind: (False, "Hourly limit for AI search."),
    )
    monkeypatch.setattr(
        llm, "nl_search", lambda *_a, **_k: pytest.fail("must not call AI")
    )
    at = _submit(_answer(_page()))
    assert any("Hourly limit for AI search." in c.value for c in at.caption)
    assert _help_cards(at)


def test_a_strict_ai_answer_is_topped_up_to_five_from_the_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSearch(monkeypatch, _result(n=1))  # the AI found only one event
    answers = {
        "division": "HS",
        "team": "Solo",
        "preference": "A project",
        "interests": (),
        "where": "In person",
    }
    at = _submit(_answer(_page(), **answers))

    assert not at.exception and len(fake.queries) == 1
    cards = [k.removeprefix("help_details_") for k in _help_cards(at)]
    assert len(cards) == 5 and cards[0] == ALL_IDS[0] and len(set(cards)) == 5
    assert "**Your top 5**" in _texts(at)
    assert any(c.value == "More that fit your answers:" for c in at.caption)
    texts = _texts(at)
    assert f"💡 *Reason for {ALL_IDS[0]}*" in texts
    assert sum(t.startswith("💡") for t in texts) == 1  # only the AI pick has a reason
    by_id = {e.id: e for e in load_events()}
    assert all(
        "HS" in by_id[i].divisions and by_id[i].participation == "Individual"
        for i in cards[1:]
    )


def test_an_empty_ai_answer_shows_matches_from_the_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSearch(monkeypatch, SearchResult(results=[], interpretation="Showing nothing."))
    at = _submit(
        _answer(
            _page(),
            division="HS",
            team="Solo",
            preference="A project",
            interests=(),
            where="In person",
        )
    )
    assert not at.exception
    assert len(_help_cards(at)) == 5
    assert not any(c.value == "More that fit your answers:" for c in at.caption)


def test_no_matches_anywhere_shows_a_helpful_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSearch(monkeypatch, SearchResult(results=[], interpretation="Showing nothing."))
    # No virtual testing events exist, so neither the AI nor the answers match anything.
    at = _submit(
        _answer(
            _page(),
            division="College",
            team="Team",
            preference="A test",
            interests=(),
            where="Virtual",
        )
    )
    assert not at.exception
    assert any("Try loosening your answers" in i.value for i in at.info)
    assert _help_cards(at) == []
