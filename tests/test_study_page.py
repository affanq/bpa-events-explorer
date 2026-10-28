from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bpa_app import llm, ratelimit
from bpa_app.data import get_event, load_events
from bpa_app.models import Quiz, QuizQuestion

STUDY_PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "study.py")
EVENT_ID = "355"  # Python Programming: a testing event with competencies


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def _page(event_id: str | None = EVENT_ID) -> AppTest:
    at = AppTest.from_file(STUDY_PAGE, default_timeout=30)
    if event_id:
        at.query_params["event"] = event_id
    return at


def _quiz(prefix: str = "Q", n: int = 3) -> Quiz:
    return Quiz(
        questions=[
            QuizQuestion(
                question=f"{prefix}{i}: what does this print?\n```python\nprint({i})\n```",
                choices=[
                    f"{prefix}{i} a",
                    f"{prefix}{i} b",
                    f"{prefix}{i} c",
                    f"{prefix}{i} $d",
                ],
                answer_index=i % 4,
                explanation=f"Because {i}. Costs $5.",
                competency="Use Python file I/O",
            )
            for i in range(n)
        ]
    )


class FakeQuiz:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, prefix="Q") -> None:
        self.calls: list[tuple] = []
        self.prefix = prefix

        def fake(event, competencies=None, n=10, difficulty="medium", avoid=None):
            self.calls.append((event.id, competencies, n, difficulty, avoid))
            return _quiz(f"{self.prefix}{len(self.calls)}-")

        monkeypatch.setattr(llm, "generate_quiz", fake)


def _generate(at: AppTest) -> AppTest:
    next(
        b for b in at.button if b.label == "Generate 10 practice questions"
    ).click().run()
    return at


def _quiz_radios(at: AppTest):
    return [r for r in at.radio if r.key and r.key.startswith("quiz_")]


def test_picker_lists_testing_events_including_open_events() -> None:
    expected = {
        f"{e.id} – {e.title}" for e in load_events() if "Testing" in e.event_type
    }
    at = _page(None).run()
    assert set(at.selectbox[0].options) == expected
    assert any(o.startswith("290 –") for o in at.selectbox[0].options)  # an Open event
    assert at.selectbox[0].value is None and not at.button


def test_page_shows_disclaimer_competencies_and_controls() -> None:
    at = _page().run()
    assert not at.exception
    assert any("not actual BPA test questions" in i.value for i in at.info)
    assert at.selectbox[0].value == "355 – Python Programming"
    competencies = next(m.value for m in at.markdown if m.value.startswith("- "))
    assert competencies.count("\n") >= 2
    assert at.multiselect[0].label.startswith("Focus on specific competencies")
    assert at.radio[0].value == "Medium"
    assert [b.label for b in at.button] == ["Generate 10 practice questions"]


def test_non_testing_event_is_explained() -> None:
    at = _page("430").run()
    assert any("isn't a testing event" in i.value for i in at.info)
    assert at.selectbox[0].value is None


def test_event_without_competencies_is_handled() -> None:
    event_id = next(
        e.id
        for e in load_events()
        if "Testing" in e.event_type and not (e.details and e.details.competencies)
    )
    at = _page(event_id).run()
    assert not at.exception
    assert any("Competencies haven't been extracted" in i.value for i in at.info)
    assert not at.button


def test_generate_renders_a_form_with_one_radio_per_question(monkeypatch) -> None:
    fake = FakeQuiz(monkeypatch)
    at = _generate(_page().run())
    assert not at.exception
    assert fake.calls == [(EVENT_ID, [], 10, "medium", None)]
    assert len(_quiz_radios(at)) == 3 and all(r.value is None for r in _quiz_radios(at))
    assert any(b.label == "Submit answers" for b in at.button)
    assert any(b.label == "New set" for b in at.button)
    assert any("not actual BPA test questions" in c.value for c in at.caption)
    assert any(
        "```python\nprint(1)\n```" in m.value for m in at.markdown
    )  # code kept intact
    assert at.session_state["quiz"]["answers"] is None


def test_options_difficulty_and_focus_are_passed_through(monkeypatch) -> None:
    fake = FakeQuiz(monkeypatch)
    at = _page().run()
    focus = get_event(EVENT_ID).details.competencies[:2]
    at.multiselect[0].set_value(focus).run()
    at.radio[0].set_value("Hard").run()
    _generate(at)
    assert fake.calls[0][1:4] == (focus, 10, "hard")


def test_submitting_shows_score_correct_answers_and_explanations(monkeypatch) -> None:
    FakeQuiz(monkeypatch)
    at = _generate(_page().run())
    radios = _quiz_radios(at)
    radios[0].set_value(0)  # correct (answer_index 0)
    radios[1].set_value(0)  # wrong (answer_index 1)
    # radios[2] left unanswered
    next(b for b in at.button if b.label == "Submit answers").click().run()

    assert not at.exception
    assert at.metric[0].value == "1 / 3"
    assert at.progress[0].value == 33  # percent, as Streamlit reports it
    assert len(_quiz_radios(at)) == 0  # results replace the form
    assert any("Correct:" in s.value for s in at.success)
    assert any(
        "You chose: Q1-1 a" in e.value and "Correct answer: Q1-1 b" in e.value
        for e in at.error
    )
    assert any("Not answered. Correct answer: Q1-2 c" in w.value for w in at.warning)
    assert sum("**Why:** Because" in m.value for m in at.markdown) == 3
    assert any("Costs \\$5." in m.value for m in at.markdown)  # $ escaped in prose
    assert any("Q1-0 a" in m.value for m in at.success)
    assert any(b.label == "New set" for b in at.button)


def test_new_set_replaces_the_quiz_and_avoids_previous_questions(monkeypatch) -> None:
    fake = FakeQuiz(monkeypatch)
    at = _generate(_page().run())
    first = [q.question for q in at.session_state["quiz"]["questions"]]
    _quiz_radios(at)[0].set_value(1)
    next(b for b in at.button if b.label == "Submit answers").click().run()
    next(b for b in at.button if b.label == "New set").click().run()

    assert len(fake.calls) == 2 and fake.calls[1][4] == first
    quiz = at.session_state["quiz"]
    assert quiz["answers"] is None and quiz["set_id"] == 2
    assert quiz["questions"][0].question.startswith("Q2-0")
    assert len(_quiz_radios(at)) == 3 and all(r.value is None for r in _quiz_radios(at))
    assert not at.metric


def test_quiz_is_kept_in_session_across_reruns(monkeypatch) -> None:
    fake = FakeQuiz(monkeypatch)
    at = _generate(_page().run())
    at.run()
    assert len(_quiz_radios(at)) == 3 and len(fake.calls) == 1


def test_quiz_for_another_event_is_not_shown(monkeypatch) -> None:
    FakeQuiz(monkeypatch)
    at = _generate(_page().run())
    other = next(
        e.id
        for e in load_events()
        if "Testing" in e.event_type
        and e.id != EVENT_ID
        and e.details
        and e.details.competencies
    )
    at.selectbox[0].select(
        next(o for o in at.selectbox[0].options if o.startswith(f"{other} –"))
    ).run()
    assert not at.exception
    assert _quiz_radios(at) == [] and not any(b.label == "New set" for b in at.button)


def test_ai_failure_shows_error_and_no_quiz(monkeypatch) -> None:
    def fail(*_a, **_k):
        raise llm.LLMError("The AI service is busy right now.")

    monkeypatch.setattr(llm, "generate_quiz", fail)
    at = _generate(_page().run())
    assert not at.exception
    assert any("busy right now" in e.value for e in at.error)
    assert "quiz" not in at.session_state


def test_rate_limit_blocks_generation(monkeypatch) -> None:
    monkeypatch.setattr(
        ratelimit, "check_and_count", lambda kind: (False, f"Blocked {kind}.")
    )
    monkeypatch.setattr(
        llm, "generate_quiz", lambda *_a, **_k: pytest.fail("must not call AI")
    )
    at = _generate(_page().run())
    assert any(w.value == "Blocked quiz." for w in at.warning)
    assert "quiz" not in at.session_state
