from factories import make_details, make_event

from bpa_app.data import HelpAnswers, match_answers, normalize_query


def test_empty_answers() -> None:
    assert HelpAnswers().is_empty()
    assert not HelpAnswers(interests=("coding",)).is_empty()
    assert HelpAnswers().to_query() == "events"


def test_every_answer_appears_in_the_query() -> None:
    answers = HelpAnswers(
        division="HS",
        participation="Individual",
        preference="speech",
        interests=("speaking", "finance"),
        format="In-Person",
    )
    assert answers.to_query() == (
        "individual events for high school students, that involve public speaking, "
        "about speaking and finance, in-person only"
    )


def test_query_phrases_for_each_choice() -> None:
    assert HelpAnswers(division="MS", participation="Team").to_query() == (
        "team events for middle school students"
    )
    assert HelpAnswers(division="College").to_query() == "events for college students"
    assert HelpAnswers(preference="test").to_query() == (
        "events, that are multiple-choice testing events"
    )
    assert HelpAnswers(preference="project", format="Virtual").to_query() == (
        "events, that are judged project events, virtual only"
    )
    assert (
        HelpAnswers(preference="presentation")
        .to_query()
        .endswith("that involve giving a presentation")
    )
    assert HelpAnswers(interests=("coding",)).to_query() == "events, about coding"
    assert (
        HelpAnswers(interests=("a", "b", "c")).to_query() == "events, about a, b and c"
    )


def test_the_query_is_short_enough_to_cache_as_is() -> None:
    answers = HelpAnswers(
        division="College",
        participation="Team",
        preference="presentation",
        interests=tuple(f"interest {i}" for i in range(6)),
        format="Virtual",
    )
    assert len(answers.to_query()) < 300
    assert normalize_query(answers.to_query()) == answers.to_query().lower()


def test_filter_kwargs() -> None:
    assert HelpAnswers().filter_kwargs() == {
        "formats": None,
        "participation": None,
        "event_types": None,
        "divisions": None,
    }
    assert HelpAnswers(
        division="MS", participation="Team", preference="test", format="Virtual"
    ).filter_kwargs() == {
        "formats": ["Virtual"],
        "participation": ["Team"],
        "event_types": ["Testing"],
        "divisions": ["MS"],
    }
    assert HelpAnswers(format="In-Person", preference="speech").filter_kwargs() == {
        "formats": ["In-Person", "Open"],
        "participation": None,
        "event_types": ["Judged"],
        "divisions": None,
    }


def _events():
    return [
        make_event("100", "Accounting Test", divisions=["HS"], event_type=["Testing"]),
        make_event(
            "430",
            "Video Production Team",
            make_details("Teams make a film.", ["video", "editing"]),
            participation="Team",
            event_type=["Judged"],
            divisions=["HS"],
        ),
        make_event(
            "960",
            "Visual Design Team",
            make_details("Design a poster.", ["design"]),
            participation="Team",
            event_type=["Judged"],
            divisions=["MS"],
        ),
        make_event(
            "V02",
            "Virtual Promo",
            make_details("A virtual promo video.", ["video"]),
            format="Virtual",
            participation="Team",
            event_type=["Judged"],
            divisions=["MS", "HS"],
        ),
    ]


def ids(events) -> list[str]:
    return [e.id for e in events]


def test_match_answers_filters_then_ranks_by_interests() -> None:
    answers = HelpAnswers(division="HS", participation="Team", interests=("video",))
    assert ids(match_answers(_events(), answers)) == ["430", "V02"]


def test_match_answers_puts_interest_matches_first_but_keeps_the_rest() -> None:
    answers = HelpAnswers(division="HS", interests=("video",))
    assert ids(match_answers(_events(), answers)) == ["430", "V02", "100"]


def test_match_answers_without_interests_returns_the_filtered_events() -> None:
    assert ids(match_answers(_events(), HelpAnswers(division="MS"))) == ["960", "V02"]
    assert ids(match_answers(_events(), HelpAnswers(format="Virtual"))) == ["V02"]
    assert ids(match_answers(_events(), HelpAnswers(preference="test"))) == ["100"]
    assert match_answers(_events(), HelpAnswers(division="College")) == []
