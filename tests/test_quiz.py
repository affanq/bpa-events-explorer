import random

import pytest
from factories import make_details, make_event

from bpa_app import config, llm
from bpa_app.models import Quiz, QuizQuestion
from bpa_app.prompts import quiz_prompt
from bpa_app.ui import escape_md_keep_code

COMPETENCIES = [
    "Apply the accounting equation to analyze transactions",
    "Use Python file I/O to read, write and manage data in applications",
]


def question(
    text="What is 2 + 2?", choices=("1", "2", "3", "4"), answer=3, **kw
) -> QuizQuestion:
    return QuizQuestion(
        question=text,
        choices=list(choices),
        answer_index=answer,
        explanation=kw.get("explanation", " Because. "),
        competency=kw.get("competency", COMPETENCIES[0]),
    )


@pytest.fixture
def event():
    details = make_details("A test event.")
    details.competencies = COMPETENCIES
    return make_event(
        "355", "Python Programming", details, subject="Digital Technology"
    )


# --- prompt ------------------------------------------------------------------


def test_prompt_lists_competencies_guideline_difficulty_and_rules(event) -> None:
    prompt = quiz_prompt(event, COMPETENCIES, 10, "hard", "## Page 1\nGuideline body")
    assert "355 Python Programming" in prompt
    assert all(f"- {c}" in prompt for c in COMPETENCIES)
    assert "## Page 1\nGuideline body" in prompt
    assert "exactly 10 questions at hard difficulty" in prompt
    assert "multi-step reasoning" in prompt
    assert "fenced markdown code block" in prompt and "exactly 4" in prompt
    assert "earlier questions" not in prompt


def test_prompt_lists_questions_to_avoid_and_handles_missing_guideline(event) -> None:
    prompt = quiz_prompt(event, COMPETENCIES, 5, "easy", None, ["What is\nX?", "Y?"])
    assert "Do not repeat or closely paraphrase these earlier questions" in prompt
    assert "  - What is X?" in prompt and "  - Y?" in prompt
    assert "guideline text is not available" in prompt


# --- cleaning ----------------------------------------------------------------


def test_clean_quiz_drops_malformed_and_duplicate_questions() -> None:
    quiz = Quiz(
        questions=[
            question("Valid one?"),
            question("valid ONE?"),  # duplicate of the first
            question("Three choices?", choices=("a", "b", "c")),
            question("Repeated choice?", choices=("a", "a", "b", "c")),
            question("Blank choice?", choices=("a", " ", "b", "c")),
            question("Bad index high?", answer=4),
            question("Bad index low?", answer=-1),
            question("   "),
            question("Valid two?"),
        ]
    )
    cleaned = llm.clean_quiz(quiz, COMPETENCIES, 10, random.Random(0))
    assert [q.question for q in cleaned.questions] == ["Valid one?", "Valid two?"]


def test_clean_quiz_caps_at_n_and_keeps_the_correct_answer_after_shuffling() -> None:
    quiz = Quiz(
        questions=[
            question(f"Question {i}?", choices=("w1", "w2", "right", "w3"), answer=2)
            for i in range(30)
        ]
    )
    cleaned = llm.clean_quiz(quiz, COMPETENCIES, 10, random.Random(1))
    assert len(cleaned.questions) == 10
    assert all(q.choices[q.answer_index] == "right" for q in cleaned.questions)
    assert len({q.answer_index for q in cleaned.questions}) > 1  # really shuffled


def test_questions_with_order_dependent_choices_are_not_shuffled() -> None:
    choices = ("Only A", "Only B", "Both A and B", "None of the above")
    cleaned = llm.clean_quiz(
        Quiz(questions=[question(choices=choices, answer=2)]), COMPETENCIES, 10
    )
    assert cleaned.questions[0].choices == list(choices)
    assert cleaned.questions[0].answer_index == 2


def test_clean_quiz_matches_competencies_and_trims_text() -> None:
    quiz = Quiz(
        questions=[
            question(
                "Q1?",
                competency="apply the accounting equation to analyze transactions.",
            ),
            question(
                "Q2?", competency="Use Python file I/O to read, write and manage data"
            ),
            question("Q3?", competency="Something else"),
        ]
    )
    cleaned = llm.clean_quiz(quiz, COMPETENCIES, 10)
    assert [q.competency for q in cleaned.questions] == [
        COMPETENCIES[0],
        COMPETENCIES[1],
        "Something else",
    ]
    assert cleaned.questions[0].explanation == "Because."


def test_clean_quiz_with_nothing_usable_raises() -> None:
    with pytest.raises(llm.LLMError, match="usable questions"):
        llm.clean_quiz(Quiz(questions=[question(choices=("a", "b"))]), COMPETENCIES, 10)
    with pytest.raises(llm.LLMError, match="usable questions"):
        llm.clean_quiz(Quiz(questions=[]), COMPETENCIES, 10)


# --- generate_quiz -----------------------------------------------------------


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    def fake(prompt, schema, **kwargs):
        seen.update(prompt=prompt, schema=schema, **kwargs)
        return Quiz(questions=[question(f"Q{i}?") for i in range(12)])

    monkeypatch.setattr(llm, "generate_structured", fake)
    return seen


def test_generate_quiz_uses_fast_model_and_returns_n_questions(event, captured) -> None:
    quiz = llm.generate_quiz(event, None, 10, "easy")
    assert len(quiz.questions) == 10
    assert captured["model"] == config.MODEL_FAST and captured["schema"] is Quiz
    assert "exactly 10 questions at easy difficulty" in captured["prompt"]
    assert all(f"- {c}" in captured["prompt"] for c in COMPETENCIES)


def test_generate_quiz_can_focus_on_chosen_competencies(event, captured) -> None:
    llm.generate_quiz(event, [COMPETENCIES[1], "not an event competency"], 5, "medium")
    assert f"- {COMPETENCIES[1]}" in captured["prompt"]
    assert f"- {COMPETENCIES[0]}" not in captured["prompt"]


def test_generate_quiz_passes_avoid_list(event, captured) -> None:
    llm.generate_quiz(event, None, 5, "medium", avoid=["Old question?"])
    assert "  - Old question?" in captured["prompt"]


def test_generate_quiz_rejects_events_without_competencies(captured) -> None:
    with pytest.raises(llm.LLMError, match="no competencies"):
        llm.generate_quiz(make_event("1", "No details"), None, 10, "medium")
    with pytest.raises(llm.LLMError, match="no competencies"):
        llm.generate_quiz(make_event("2", "Empty", make_details()), None, 10, "medium")
    assert captured == {}


def test_generate_quiz_rejects_unknown_difficulty(event, captured) -> None:
    with pytest.raises(ValueError, match="difficulty"):
        llm.generate_quiz(event, None, 10, "impossible")


# --- markdown escaping -------------------------------------------------------


def test_escape_md_keep_code_only_escapes_outside_code() -> None:
    text = "Costs $5 and `echo $HOME` then\n```bash\nprice=$10\n```\nend $9"
    assert escape_md_keep_code(text) == (
        "Costs \\$5 and `echo $HOME` then\n```bash\nprice=$10\n```\nend \\$9"
    )
    assert escape_md_keep_code("no dollars") == "no dollars"
