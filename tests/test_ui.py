from factories import make_details, make_event

from bpa_app.ui import badges, checklist_markdown, escape_md, team_size_text


def _team(details=None, **kw):
    return make_event(
        "430", "Video Production Team", details, participation="Team", **kw
    )


def test_team_size_text() -> None:
    assert team_size_text(make_event("1", "Solo")) == "Individual event"
    both = make_details()
    both.team_size_min, both.team_size_max = 2, 4
    assert team_size_text(_team(both)) == "2–4 members"
    same = make_details()
    same.team_size_min = same.team_size_max = 3
    assert team_size_text(_team(same)) == "3 members"
    only_max = make_details()
    only_max.team_size_max = 4
    assert team_size_text(_team(only_max)) == "Up to 4 members"
    only_min = make_details()
    only_min.team_size_min = 2
    assert team_size_text(_team(only_min)) == "At least 2 members"
    assert team_size_text(_team(make_details())) == "Team size not stated"
    assert team_size_text(_team(None)) == "Team size not stated"


def test_escape_md_protects_dollar_signs() -> None:
    assert escape_md("$10 fee, $20 late") == "\\$10 fee, \\$20 late"


def test_badges_include_flags() -> None:
    event = make_event(
        "1", "T", certification=True, presubmit=True, event_type=["Testing", "Judged"]
    )
    text = badges(event)
    assert ":blue-badge[In-Person]" in text and ":orange-badge[Judged]" in text
    assert "Certification" in text and "Presubmit" in text
    assert "Certification" not in badges(make_event("2", "T", certification=False))


def test_checklist_markdown_tracks_checked_items_and_skips_empty_sections() -> None:
    event = make_event("430", "Video Production Team", view_url="https://example.com/p")
    sections = {
        "What to submit": ["Video link", "Script"],
        "Pre-submit items": [],
        "What to bring": ["Laptop"],
    }
    done = {"What to submit-0": True, "What to bring-0": False}
    assert checklist_markdown(event, sections, done) == (
        "# Checklist: 430 Video Production Team\n"
        "\n"
        "## What to submit\n"
        "\n"
        "- [x] Video link\n"
        "- [ ] Script\n"
        "\n"
        "## What to bring\n"
        "\n"
        "- [ ] Laptop\n"
        "\n"
        "Official guideline: https://example.com/p\n"
    )
