from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bpa_app import llm, ratelimit
from bpa_app.data import load_events
from bpa_app.models import CriterionScore, Evaluation

EVALUATE_PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "evaluate.py")


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def _page(event_id: str | None = "430") -> AppTest:
    at = AppTest.from_file(EVALUATE_PAGE, default_timeout=30)
    if event_id:
        at.query_params["event"] = event_id
    return at


def _fake_evaluation() -> Evaluation:
    return Evaluation(
        criteria=[
            CriterionScore(
                criterion="Creativity & Originality",
                max_points=25,
                estimated_points=14,
                evidence="Fresh ideas in scene 2.",
                suggestions="Add a personal voice. $5 budget",
            ),
            CriterionScore(
                criterion="Topic Development",
                max_points=25,
                estimated_points=18,
                evidence="Clear.",
                suggestions="More detail.",
            ),
        ],
        missing_requirements=["Works Cited"],
        strengths=["Clear topic"],
        top_3_improvements=["Add Works Cited", "Deepen scenes", "Add URL"],
        estimated_total=32,
        max_total=50,
        cannot_assess=["Live delivery"],
    )


class FakeEvaluate:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple] = []

        def fake(event, text, pdf, notes="", sections=None):
            self.calls.append((event.id, text, pdf, notes, sections))
            return _fake_evaluation()

        monkeypatch.setattr(llm, "evaluate_submission", fake)


def _evaluate(at: AppTest) -> AppTest:
    next(b for b in at.button if b.label == "Evaluate my draft").click().run()
    return at


def test_page_shows_notices_rubric_and_inputs() -> None:
    at = _page().run()
    assert not at.exception
    assert at.title[0].value == "Evaluate a submission"
    assert any(
        "Practice estimate only – actual judges' scores will differ." in w.value
        for w in at.warning
    )
    assert any(
        "not stored by this app" in i.value and "personal information" in i.value
        for i in at.info
    )
    assert at.selectbox[0].value == "430 – Video Production Team"
    assert len(at.dataframe) == 1 and len(at.file_uploader) == 1
    assert [t.label for t in at.text_area][1].startswith(
        "Anything the judge should know?"
    )
    assert not next(b for b in at.button if b.label == "Evaluate my draft").disabled


def test_clicking_without_content_asks_for_a_file_or_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEvaluate(monkeypatch)
    at = _evaluate(_page().run())
    assert not at.exception
    assert any("upload a file or paste your text" in w.value for w in at.warning)
    assert fake.calls == []
    assert "ai_call_times_evaluation" not in at.session_state


def test_picker_only_lists_events_with_a_rubric() -> None:
    expected = {
        f"{e.id} – {e.title}" for e in load_events() if e.details and e.details.rubric
    }
    at = _page(None).run()
    assert set(at.selectbox[0].options) == expected
    assert at.selectbox[0].value is None  # nothing chosen: page stops here
    assert len(at.file_uploader) == 0


def test_event_without_rubric_in_url_explains_and_shows_picker() -> None:
    no_rubric = next(e.id for e in load_events() if e.details and not e.details.rubric)
    at = _page(no_rubric).run()
    assert any("no scoring rubric" in i.value for i in at.info)
    assert at.selectbox[0].value is None


def test_multi_rubric_event_defaults_to_first_section() -> None:
    at = _page().run()
    assert at.multiselect[0].value == ["Technical Scoring Rubric"]


def test_evaluating_pasted_text_shows_full_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEvaluate(monkeypatch)
    at = _page().run()
    at.text_area[0].set_value("My script about screens").run()
    at.text_area[1].set_value("The video is separate").run()
    _evaluate(at)

    assert not at.exception
    assert fake.calls == [
        (
            "430",
            "My script about screens",
            None,
            "The video is separate",
            ["Technical Scoring Rubric"],
        )
    ]
    assert at.metric[0].value == "32 / 50"
    assert at.progress[0].value == 64
    labels = [e.label for e in at.expander]
    assert (
        "Creativity & Originality — 14 / 25" in labels
        and "Topic Development — 18 / 25" in labels
    )
    assert [w.value for w in at.warning if w.value == "Works Cited"] == ["Works Cited"]
    assert any("Not scored" in i.value and "Live delivery" in i.value for i in at.info)
    assert any(
        m.value == "1. Add Works Cited\n2. Deepen scenes\n3. Add URL"
        for m in at.markdown
    )
    assert any(
        "Add a personal voice. \\$5 budget" in m.value for m in at.markdown
    )  # $ escaped
    # Only the feedback is kept in the session, not the submission.
    assert set(at.session_state["evaluation"]) == {"event_id", "result"}
    assert len(at.session_state["ai_call_times_evaluation"]) == 1


def test_result_survives_reruns_without_another_ai_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEvaluate(monkeypatch)
    at = _page().run()
    at.text_area[0].set_value("draft").run()
    _evaluate(at)
    at.run()
    assert at.metric[0].value == "32 / 50"
    assert len(fake.calls) == 1


def test_uploaded_file_is_read_and_preferred_over_pasted_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEvaluate(monkeypatch)
    at = _page().run()
    at.file_uploader[0].set_value(
        ("draft.md", b"# Uploaded draft", "text/markdown")
    ).run()
    at.text_area[0].set_value("pasted text").run()
    assert any("uploaded file will be used" in c.value for c in at.caption)
    _evaluate(at)
    assert fake.calls[0][1] == "# Uploaded draft"
    assert fake.calls[0][2] is None  # only PDFs pass their bytes


def test_uploaded_pdf_passes_text_and_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Draft in a PDF")
    pdf = doc.tobytes()

    fake = FakeEvaluate(monkeypatch)
    at = _page().run()
    at.file_uploader[0].set_value(("draft.pdf", pdf, "application/pdf")).run()
    _evaluate(at)
    _event_id, text, sent_pdf, *_ = fake.calls[0]
    assert "Draft in a PDF" in text and sent_pdf == pdf


def test_unreadable_upload_shows_friendly_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEvaluate(monkeypatch)
    at = _page().run()
    at.file_uploader[0].set_value(
        ("bad.pdf", b"not a real pdf", "application/pdf")
    ).run()
    _evaluate(at)
    assert not at.exception
    assert any("Could not read this PDF" in e.value for e in at.error)
    assert fake.calls == []


def test_ai_failure_shows_error_and_no_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_a, **_k):
        raise llm.LLMError("The AI service is busy right now.")

    monkeypatch.setattr(llm, "evaluate_submission", fail)
    at = _page().run()
    at.text_area[0].set_value("draft").run()
    _evaluate(at)
    assert not at.exception
    assert any("busy right now" in e.value for e in at.error)
    assert "evaluation" not in at.session_state


def test_evaluations_are_limited_to_five_per_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEvaluate(monkeypatch)
    at = _page().run()
    at.text_area[0].set_value("draft").run()
    for _ in range(5):
        _evaluate(at)
    assert len(fake.calls) == 5
    _evaluate(at)
    assert len(fake.calls) == 5
    assert any("hourly limit for AI evaluation" in w.value for w in at.warning)


def test_rate_limit_blocks_the_ai_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ratelimit, "check_and_count", lambda kind: (False, f"Blocked {kind}.")
    )
    monkeypatch.setattr(
        llm, "evaluate_submission", lambda *_a, **_k: pytest.fail("must not call AI")
    )
    at = _page().run()
    at.text_area[0].set_value("draft").run()
    _evaluate(at)
    assert any(w.value == "Blocked evaluation." for w in at.warning)
