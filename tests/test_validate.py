from bpa_app import data
from bpa_app.models import Event, EventDetails, RubricItem, SectionTotal


def _details(**overrides) -> EventDetails:
    base = {
        "summary": "A short summary.",
        "team_size_min": None,
        "team_size_max": None,
        "time_limits": [],
        "submission_requirements": [],
        "presubmit_items": [],
        "deadlines": [],
        "what_to_bring": [],
        "competencies": [],
        "rubric": [],
        "rubric_total_points": None,
        "judging_notes": [],
        "eligibility_notes": [],
        "keywords": [],
    }
    return EventDetails(**{**base, **overrides})


def _event(details: EventDetails | None, **overrides) -> Event:
    base = {
        "id": "430",
        "title": "Video Production Team",
        "subject": "Digital Media",
        "format": "In-Person",
        "participation": "Individual",
        "event_type": ["Judged"],
        "divisions": ["HS"],
        "certification": None,
        "presubmit": None,
        "regional_deadline": None,
        "nlc_deadline": None,
        "view_url": None,
        "download_url": None,
        "pdf_file": "430.pdf",
        "has_text": True,
        "details": details,
    }
    return Event(**{**base, **overrides})


def _item(points: float | None, section: str | None = None) -> RubricItem:
    return RubricItem(
        section=section, criterion="c", max_points=points, description=None
    )


def _kinds(event: Event) -> list[str]:
    return [p.kind for p in data.find_problems([event])]


def test_clean_event_has_no_problems() -> None:
    details = _details(rubric=[_item(10), _item(15)], rubric_total_points=25)
    assert _kinds(_event(details)) == []


def test_missing_text_and_details() -> None:
    event = _event(None, has_text=False, pdf_file=None)
    problems = data.find_problems([event])
    assert [p.kind for p in problems] == [data.MISSING_TEXT, data.MISSING_DETAILS]
    assert problems[0].detail == "no local PDF"


def test_judged_event_with_empty_rubric() -> None:
    assert _kinds(_event(_details())) == [data.EMPTY_RUBRIC]


def test_testing_only_event_may_have_empty_rubric() -> None:
    assert _kinds(_event(_details(), event_type=["Testing"])) == []


def test_rubric_total_mismatch() -> None:
    details = _details(
        rubric=[_item(10), _item(None), _item(15)], rubric_total_points=280
    )
    problems = data.find_problems([_event(details)])
    assert [p.kind for p in problems] == [data.TOTAL_MISMATCH]
    assert problems[0].detail == "overall: stated 280, items sum to 25"


def test_section_totals_are_checked_per_rubric() -> None:
    rubric = [
        _item(10, "Technical"),
        _item(15, "Technical"),
        _item(5, "Presentation"),
    ]
    ok = _details(
        rubric=rubric,
        rubric_section_totals=[
            SectionTotal(section="Technical", total_points=25),
            SectionTotal(section="presentation ", total_points=5),
        ],
    )
    assert _kinds(_event(ok)) == []

    bad = _details(
        rubric=rubric,
        rubric_section_totals=[SectionTotal(section="Technical", total_points=280)],
    )
    problems = data.find_problems([_event(bad)])
    assert [p.detail for p in problems] == ["Technical: stated 280, items sum to 25"]


def test_team_event_needs_team_size() -> None:
    details = _details(rubric=[_item(5)], team_size_min=2)
    assert _kinds(_event(details, participation="Team")) == [data.NO_TEAM_SIZE]
    ok = _details(rubric=[_item(5)], team_size_min=2, team_size_max=4)
    assert _kinds(_event(ok, participation="Team")) == []


def test_mentions_testing() -> None:
    assert data.mentions_testing(_details(time_limits=["Test: 60 minutes"]))
    assert data.mentions_testing(
        _details(summary="Includes a multiple-choice section.")
    )
    assert data.mentions_testing(_details(summary="A judged video project.")) is None
