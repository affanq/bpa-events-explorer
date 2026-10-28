from bpa_app.models import Event, EventDetails


def make_details(summary: str = "", keywords=(), competencies=()) -> EventDetails:
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


def make_event(
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
