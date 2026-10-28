from pathlib import Path

import pytest
from factories import make_event
from streamlit.testing.v1 import AppTest

from bpa_app import config
from bpa_app.data import load_events
from bpa_app.ui import (
    GUIDELINES_RELEASE,
    REPORT_SUBJECT,
    guideline_links_dataframe,
    report_error_link,
)

ABOUT_PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "about.py")


def _page() -> AppTest:
    return AppTest.from_file(ABOUT_PAGE, default_timeout=30).run()


def _text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown]
    parts += [w.value for w in at.warning] + [i.value for i in at.info]
    parts += [c.value for c in at.caption] + [h.value for h in at.header]
    return "\n".join(parts)


def test_report_error_link_is_a_mailto_with_a_subject() -> None:
    link = report_error_link("help@example.org")
    assert (
        link
        == "mailto:help@example.org?subject=BPA%20Event%20Explorer%3A%20data%20error"
    )
    assert REPORT_SUBJECT in "BPA Event Explorer: data error"


def test_report_error_link_defaults_to_the_configured_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "REPORT_EMAIL", "owner@example.org")
    assert report_error_link().startswith("mailto:owner@example.org?subject=")


def test_guideline_links_dataframe() -> None:
    events = [
        make_event(
            "100", "Accounting", view_url="https://example.com/a", divisions=["HS"]
        ),
        make_event("190", "No PDF", divisions=["HS", "College"]),
    ]
    frame = guideline_links_dataframe(events)
    assert list(frame.columns) == ["Event", "Title", "Divisions", "Official PDF"]
    assert frame["Official PDF"].tolist()[0] == "https://example.com/a"
    assert frame["Official PDF"].isna().tolist() == [False, True]
    assert frame["Divisions"].tolist() == ["HS", "HS/College"]


def test_page_has_every_requested_section() -> None:
    at = _page()
    assert not at.exception
    assert [h.value for h in at.header] == [
        "What this app does",
        "Where the data comes from",
        "AI features",
        "Privacy",
        "Report a data error",
    ]
    text = _text(at)
    assert "not an official BPA product" in text
    assert "2026-2027" in text and GUIDELINES_RELEASE in text
    assert (
        "Uploads are not stored" in text
        and "Please don't include personal information" in text
    )
    assert "AI-generated – may contain errors" in text
    assert "Practice estimate only" in text and "not actual BPA test questions" in text


def test_every_event_pdf_is_listed() -> None:
    at = _page()
    assert [e.label for e in at.expander] == ["Official guideline PDFs"]
    assert len(at.dataframe) == 1
    frame = at.dataframe[0].value
    assert len(frame) == len(load_events())
    assert frame["Official PDF"].notna().sum() == sum(
        bool(e.view_url) for e in load_events()
    )


def test_privacy_notice_names_the_active_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_GEMINI)
    assert "**Google Gemini**" in _text(_page())
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_CORTEX)
    assert "Cortex" in _text(_page())


def test_report_button_uses_the_configured_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "REPORT_EMAIL", "owner@example.org")
    at = _page()
    buttons = at.get("link_button")
    assert len(buttons) == 1
    assert buttons[0].proto.url.startswith("mailto:owner@example.org?subject=")
    assert "isn't set up yet" not in _text(at)


def test_placeholder_address_is_flagged_for_the_site_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "REPORT_EMAIL", config.PLACEHOLDER_REPORT_EMAIL)
    at = _page()
    assert at.get("link_button")[0].proto.url.startswith(
        f"mailto:{config.PLACEHOLDER_REPORT_EMAIL}"
    )
    assert "isn't set up yet" in _text(at)
