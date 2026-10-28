from pathlib import Path

import pytest
import streamlit as st
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from bpa_app import data

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def test_app_starts_on_the_browse_page() -> None:
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "🏆 BPA Event Explorer"
    assert not at.error


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("events.json"),
        ValueError("bad json"),
        ValidationError.from_exception_data("Event", []),
    ],
    ids=["missing", "invalid-json", "invalid-schema"],
)
def test_missing_or_broken_data_shows_a_friendly_message(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def broken(*_a, **_k):
        raise failure

    monkeypatch.setattr(data, "load_events", broken)
    at = AppTest.from_file(APP, default_timeout=30).run()

    assert not at.exception
    assert any("event data isn't available" in e.value for e in at.error)
    assert not at.button and not at.selectbox  # nothing else is rendered
    assert not any("Traceback" in e.value for e in at.error)
