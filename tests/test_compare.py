from pathlib import Path

import pytest
import streamlit as st
from factories import make_details, make_event
from streamlit.testing.v1 import AppTest

from bpa_app.data import load_events
from bpa_app.models import SectionTotal
from bpa_app.ui import (
    COMPARE_FIELDS,
    NOT_AVAILABLE,
    NOT_STATED,
    rubric_total_lines,
    yes_no,
)

COMPARE_PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "compare.py")


# --- field helpers -----------------------------------------------------------


def test_field_order_matches_the_requested_comparison() -> None:
    assert list(COMPARE_FIELDS) == [
        "Format",
        "Participation",
        "Team size",
        "Type",
        "Divisions",
        "Time limits",
        "Submission requirements",
        "Presubmit",
        "Pre-submit items",
        "Certification",
        "Rubric total",
    ]


def test_yes_no() -> None:
    assert [yes_no(True), yes_no(False), yes_no(None)] == ["Yes", "No", NOT_STATED]


def test_fields_for_an_event_with_details() -> None:
    details = make_details("Teams make a video.")
    details.team_size_min, details.team_size_max = 2, 4
    details.time_limits = ["Setup: 3 minutes", "Presentation: 10 minutes"]
    details.submission_requirements = ["Video URL"]
    details.presubmit_items = ["Release form"]
    event = make_event(
        "430",
        "Video Production Team",
        details,
        format="In-Person",
        participation="Team",
        event_type=["Judged"],
        divisions=["MS", "HS", "College"],
        certification=False,
        presubmit=True,
    )
    values = {name: getter(event) for name, getter in COMPARE_FIELDS.items()}
    assert values["Format"] == ["In-Person"]
    assert values["Participation"] == ["Team"]
    assert values["Team size"] == ["2–4 members"]
    assert values["Type"] == ["Judged"]
    assert values["Divisions"] == ["Middle School (MS), High School (HS), College"]
    assert values["Time limits"] == ["Setup: 3 minutes", "Presentation: 10 minutes"]
    assert values["Submission requirements"] == ["Video URL"]
    assert values["Presubmit"] == ["Yes"] and values["Pre-submit items"] == [
        "Release form"
    ]
    assert values["Certification"] == ["No"]


def test_testing_and_judged_types_are_joined() -> None:
    event = make_event("1", "Both", event_type=["Testing", "Judged"])
    assert COMPARE_FIELDS["Type"](event) == ["Testing / Judged"]


def test_events_without_details_say_not_available() -> None:
    event = make_event("755", "Prepared Speech")
    for name in (
        "Time limits",
        "Submission requirements",
        "Pre-submit items",
        "Rubric total",
    ):
        assert COMPARE_FIELDS[name](event) == [NOT_AVAILABLE]
    assert COMPARE_FIELDS["Presubmit"](event) == [NOT_STATED]  # catalog value unknown
    assert COMPARE_FIELDS["Team size"](event) == ["Individual event"]


def test_empty_detail_lists_say_not_stated() -> None:
    event = make_event("1", "Empty", make_details())
    assert COMPARE_FIELDS["Time limits"](event) == [NOT_STATED]
    assert COMPARE_FIELDS["Pre-submit items"](event) == [NOT_STATED]


def test_rubric_total_lines_prefers_stated_totals() -> None:
    details = make_details()
    details.rubric_total_points = 400
    details.rubric_section_totals = [
        SectionTotal(section="Technical", total_points=300),
        SectionTotal(section="Presentation", total_points=100),
    ]
    assert rubric_total_lines(make_event("1", "A", details)) == [
        "400 points in total",
        "Technical: 300",
        "Presentation: 100",
    ]
    details.rubric_total_points = None
    assert rubric_total_lines(make_event("1", "A", details)) == [
        "Technical: 300",
        "Presentation: 100",
    ]


def test_rubric_total_falls_back_to_sum_then_testing_then_not_stated() -> None:
    from bpa_app.models import RubricItem

    details = make_details()
    details.rubric = [
        RubricItem(section=None, criterion="a", max_points=10, description=None),
        RubricItem(section=None, criterion="b", max_points=None, description=None),
        RubricItem(section=None, criterion="c", max_points=15.5, description=None),
    ]
    assert rubric_total_lines(make_event("1", "A", details)) == [
        "25.5 (sum of listed items)"
    ]
    assert rubric_total_lines(
        make_event("2", "T", make_details(), event_type=["Testing"])
    ) == ["No rubric (testing event)"]
    assert rubric_total_lines(
        make_event("3", "J", make_details(), event_type=["Judged"])
    ) == [NOT_STATED]


# --- page --------------------------------------------------------------------

GROUPS = {
    "Graphic Design": ["410", "945"],
    "Video": ["430", "950"],
    "Website": ["365", "955", "V04"],
    "Visual Design": ["460", "960"],
    "Speech": ["735", "755", "975", "980"],
    "Interview": ["725", "730", "V15"],
}


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    st.cache_data.clear()


def _page(event_id: str | None = None) -> AppTest:
    at = AppTest.from_file(COMPARE_PAGE, default_timeout=30)
    if event_id:
        at.query_params["event"] = event_id
    return at


def _texts(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown] + [c.value for c in at.caption]


def _field_labels(at: AppTest) -> list[str]:
    labels = {f":blue[**{name}**]": name for name in COMPARE_FIELDS}
    return [labels[m.value] for m in at.markdown if m.value in labels]


def test_quick_pick_groups_exist_in_the_catalog() -> None:
    known = {e.id for e in load_events()}
    assert all(set(ids) <= known for ids in GROUPS.values())


def test_page_starts_empty_with_all_quick_picks() -> None:
    at = _page().run()
    assert not at.exception
    assert [b.label for b in at.button] == list(GROUPS)
    assert any("Choose at least 2 events (up to 4)" in i.value for i in at.info)
    assert at.multiselect[0].value == []


@pytest.mark.parametrize("group", list(GROUPS))
def test_each_quick_pick_selects_its_events_and_renders(group: str) -> None:
    at = _page().run()
    next(b for b in at.button if b.label == group).click().run()
    assert not at.exception
    assert at.multiselect[0].value == GROUPS[group]
    assert len([b for b in at.button if b.label == "Details"]) == len(GROUPS[group])
    assert _field_labels(at) == list(COMPARE_FIELDS)


def test_event_options_include_the_division_to_tell_twin_events_apart() -> None:
    at = _page().run()
    options = at.multiselect[0].options
    assert "945 – Graphic Design Promotion · MS" in options
    assert "410 – Graphic Design Promotion · HS/College" in options


def test_comparison_shows_each_events_values_side_by_side() -> None:
    at = _page().run()
    next(b for b in at.button if b.label == "Video").click().run()
    texts = _texts(at)
    assert "**Video Production Team**" in texts
    assert "Event 430 · HS/College" in texts and "Event 950 · MS" in texts
    assert texts.count("Team") == 2 and texts.count("In-Person") == 2
    assert texts.count("2–4 members") == 2
    assert "Technical Scoring Rubric: 280" in "\n".join(texts)


def test_event_without_details_is_shown_as_not_available() -> None:
    at = _page().run()
    next(b for b in at.button if b.label == "Speech").click().run()
    assert not at.exception
    assert NOT_AVAILABLE in _texts(at)  # 755 has no extracted details


def test_one_event_is_not_enough_to_compare() -> None:
    at = _page().run()
    at.multiselect[0].set_value(["430"]).run()
    assert any("at least 2 events" in i.value for i in at.info)
    assert _field_labels(at) == []


def test_event_in_url_is_preselected() -> None:
    at = _page("430").run()
    assert at.multiselect[0].value == ["430"]
    assert not _page("not-an-event").run().multiselect[0].value


def test_selection_order_is_kept_and_survives_reruns() -> None:
    at = _page().run()
    at.multiselect[0].set_value(["950", "430", "365"]).run()
    assert [
        m.value for m in at.markdown if m.value.startswith("**") and "Team" in m.value
    ][:3] == [
        "**Video Production Team**",
        "**Video Production Team**",
        "**Website Design and Development Team**",
    ]
    at.run()
    assert at.multiselect[0].value == ["950", "430", "365"]
