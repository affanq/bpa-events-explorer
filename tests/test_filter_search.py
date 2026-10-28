import pytest

from bpa_app import data
from bpa_app.models import Event, EventDetails


def _details(summary: str = "", keywords=(), competencies=()) -> EventDetails:
    return EventDetails(
        summary=summary,
        team_size_min=None,
        team_size_max=None,
        time_limits=[],
        submission_requirements=[],
        presubmit_items=[],
        deadlines=[],
        what_to_bring=[],
        competencies=list(competencies),
        rubric=[],
        rubric_total_points=None,
        judging_notes=[],
        eligibility_notes=[],
        keywords=list(keywords),
    )


def _event(
    event_id: str, title: str, details: EventDetails | None = None, **kw
) -> Event:
    base = {
        "id": event_id,
        "title": title,
        "subject": "Finance",
        "format": "In-Person",
        "participation": "Individual",
        "event_type": ["Testing"],
        "divisions": ["HS"],
        "certification": None,
        "presubmit": None,
        "regional_deadline": None,
        "nlc_deadline": None,
        "view_url": None,
        "download_url": None,
        "pdf_file": None,
        "has_text": False,
        "details": details,
    }
    return Event(**{**base, **kw})


@pytest.fixture
def events() -> list[Event]:
    return [
        _event("100", "Fundamental Accounting", certification=False),
        _event(
            "430",
            "Video Production Team",
            _details(
                "Teams make a short film.", ["video", "editing"], ["storyboarding"]
            ),
            subject="Digital Media",
            participation="Team",
            event_type=["Judged"],
            divisions=["MS", "HS"],
            certification=True,
            presubmit=True,
        ),
        _event(
            "V02",
            "Virtual Multimedia & Promotion",
            _details(
                "A promotional video about athletes.", ["promotion"], ["audio editing"]
            ),
            subject="Virtual",
            format="Virtual",
            participation="Team",
            event_type=["Judged"],
            divisions=["MS", "HS", "College"],
        ),
        _event(
            "505",
            "Management Concepts",
            subject="Management",
            event_type=["Testing", "Judged"],
            divisions=["College"],
            presubmit=False,
        ),
    ]


def _ids(found: list[Event]) -> list[str]:
    return [e.id for e in found]


def test_no_filters_returns_everything(events: list[Event]) -> None:
    assert _ids(data.filter_events(events)) == ["100", "430", "V02", "505"]
    assert _ids(data.filter_events(events, formats=[], subjects=None)) == _ids(events)


def test_single_filters(events: list[Event]) -> None:
    assert _ids(data.filter_events(events, formats=["Virtual"])) == ["V02"]
    assert _ids(data.filter_events(events, participation=["Team"])) == ["430", "V02"]
    assert _ids(data.filter_events(events, subjects=["Management"])) == ["505"]


def test_values_within_one_filter_are_or(events: list[Event]) -> None:
    found = data.filter_events(events, formats=["Virtual", "In-Person"])
    assert len(found) == 4


def test_event_type_and_division_match_any_overlap(events: list[Event]) -> None:
    assert _ids(data.filter_events(events, event_types=["Testing"])) == ["100", "505"]
    assert _ids(data.filter_events(events, event_types=["Judged"])) == [
        "430",
        "V02",
        "505",
    ]
    assert _ids(data.filter_events(events, divisions=["College"])) == ["V02", "505"]
    assert _ids(data.filter_events(events, divisions=["MS"])) == ["430", "V02"]


def test_filters_combine_with_and(events: list[Event]) -> None:
    found = data.filter_events(events, participation=["Team"], divisions=["College"])
    assert _ids(found) == ["V02"]


def test_certification_and_presubmit_only(events: list[Event]) -> None:
    assert _ids(data.filter_events(events, certification_only=True)) == ["430"]
    assert _ids(data.filter_events(events, presubmit_only=True)) == ["430"]
    both = data.filter_events(events, certification_only=True, presubmit_only=True)
    assert _ids(both) == ["430"]


def test_search_is_case_insensitive(events: list[Event]) -> None:
    assert _ids(data.keyword_search(events, "ACCOUNTING")) == ["100"]


def test_search_ranks_title_above_keywords_above_summary(events: list[Event]) -> None:
    # "video": title x3 + keyword x2 + summary x1 for 430; summary only for V02.
    assert _ids(data.keyword_search(events, "video")) == ["430", "V02"]


def test_search_scores_keywords_and_competencies(events: list[Event]) -> None:
    assert _ids(data.keyword_search(events, "storyboarding")) == ["430"]
    assert _ids(data.keyword_search(events, "audio")) == ["V02"]
    assert _ids(data.keyword_search(events, "promotion")) == ["V02"]


def test_search_multiple_words_sum_scores(events: list[Event]) -> None:
    found = data.keyword_search(events, "video editing")
    assert _ids(found) == ["430", "V02"]


def test_search_ignores_stopwords_and_blank_queries(events: list[Event]) -> None:
    assert data.keyword_search(events, "") == []
    assert data.keyword_search(events, "the of for") == []
    assert _ids(data.keyword_search(events, "the accounting")) == ["100"]


def test_search_matches_word_starts_not_substrings(events: list[Event]) -> None:
    assert data.keyword_search(events, "ounting") == []
