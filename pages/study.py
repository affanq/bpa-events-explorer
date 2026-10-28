import streamlit as st

from bpa_app import llm
from bpa_app.data import get_event, load_events
from bpa_app.models import Event, QuizQuestion
from bpa_app.ratelimit import check_and_count
from bpa_app.ui import QUIZ_DISCLAIMER, badges, escape_md, escape_md_keep_code

QUIZ_SIZE = 10
DIFFICULTY_LABELS = ["Easy", "Medium", "Hard"]
OPTION_CHARS = 90


def choose_event(events: list[Event]) -> Event:
    """Pick a testing event; defaults to ?event=<id> when that event qualifies."""
    requested = st.query_params.get("event", "")
    index = next((i for i, e in enumerate(events) if e.id == requested), None)
    if index is None and requested and get_event(requested) is not None:
        st.info(
            f"Event {requested} isn't a testing event, so it has no practice questions. "
            "Please choose another event."
        )
    options = {f"{e.id} – {e.title}": e for e in events}
    choice = st.selectbox(
        "Testing event", list(options), index=index, placeholder="Choose an event"
    )
    if choice is None:
        st.stop()
    event = options[choice]
    st.query_params["event"] = event.id
    return event


def shorten(text: str, limit: int = OPTION_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def generate(event: Event, focus: list[str], difficulty: str) -> None:
    allowed, message = check_and_count("quiz")
    if not allowed:
        st.warning(message)
        return
    previous = st.session_state.get("quiz")
    avoid = (
        [q.question for q in previous["questions"]]
        if previous and previous["event_id"] == event.id
        else None
    )
    with st.spinner("Writing your practice questions…"):
        try:
            quiz = llm.generate_quiz(event, focus, QUIZ_SIZE, difficulty.lower(), avoid)
        except llm.LLMError as exc:
            st.error(str(exc))
            return
        except RuntimeError:
            st.error("AI practice questions are not configured.")
            return
    set_id = st.session_state.get("quiz_set_id", 0) + 1
    st.session_state["quiz_set_id"] = set_id
    st.session_state["quiz"] = {
        "event_id": event.id,
        "set_id": set_id,
        "questions": quiz.questions,
        "answers": None,  # filled in when the form is submitted
    }
    st.rerun()


def question_block(number: int, question: QuizQuestion) -> None:
    st.markdown(f"**{number}.** {escape_md_keep_code(question.question)}")


def render_form(state: dict) -> None:
    set_id = state["set_id"]
    questions: list[QuizQuestion] = state["questions"]
    with st.form(f"quiz_form_{set_id}"):
        for number, question in enumerate(questions, start=1):
            question_block(number, question)
            st.radio(
                f"Answer to question {number}",
                range(len(question.choices)),
                index=None,
                format_func=lambda i, q=question: escape_md_keep_code(q.choices[i]),
                key=f"quiz_{set_id}_{number}",
                label_visibility="collapsed",
            )
        submitted = st.form_submit_button("Submit answers", type="primary")
    if submitted:
        state["answers"] = [
            st.session_state.get(f"quiz_{set_id}_{n}")
            for n in range(1, len(questions) + 1)
        ]
        st.rerun()


def render_results(state: dict) -> None:
    questions: list[QuizQuestion] = state["questions"]
    answers: list[int | None] = state["answers"]
    score = sum(a == q.answer_index for a, q in zip(answers, questions, strict=True))
    total = len(questions)

    score_col, bar_col = st.columns([1, 2], vertical_alignment="center")
    score_col.metric("Your score", f"{score} / {total}")
    bar_col.progress(score / total, text=f"{score / total:.0%} correct")

    for number, (question, answer) in enumerate(
        zip(questions, answers, strict=True), start=1
    ):
        correct = escape_md_keep_code(question.choices[question.answer_index])
        with st.container(border=True):
            question_block(number, question)
            if answer == question.answer_index:
                st.success(f"Correct: {correct}", icon="✅")
            elif answer is None:
                st.warning(f"Not answered. Correct answer: {correct}", icon="⚠️")
            else:
                chosen = escape_md_keep_code(question.choices[answer])
                st.error(f"You chose: {chosen}\n\nCorrect answer: {correct}", icon="❌")
            st.markdown(f"**Why:** {escape_md_keep_code(question.explanation)}")
            st.caption(f"Competency: {shorten(question.competency, 120)}")


def render_quiz(event: Event, focus: list[str], difficulty: str) -> None:
    state = st.session_state.get("quiz")
    if not state or state["event_id"] != event.id:
        return
    st.divider()
    title_col, new_col = st.columns([3, 1], vertical_alignment="center")
    title_col.subheader("Practice questions")
    if new_col.button("New set", key="new_set", width="stretch"):
        generate(event, focus, difficulty)
    st.caption(QUIZ_DISCLAIMER)
    if state["answers"] is None:
        render_form(state)
    else:
        render_results(state)


st.title("Study")
st.info(QUIZ_DISCLAIMER, icon="ℹ️")

events = [e for e in load_events() if "Testing" in e.event_type]
event = choose_event(events)
st.markdown(badges(event))
competencies = event.details.competencies if event.details else []
if not competencies:
    st.info(
        "Competencies haven't been extracted for this event yet, so practice "
        "questions aren't available. Please check the official PDF."
    )
    st.stop()

st.subheader("Competencies")
st.markdown("\n".join(f"- {escape_md(c)}" for c in competencies))

focus = st.multiselect(
    "Focus on specific competencies (optional)",
    competencies,
    format_func=shorten,
    key=f"study_focus_{event.id}",
    help="Leave empty to cover all competencies.",
)
difficulty = st.radio(
    "Difficulty",
    DIFFICULTY_LABELS,
    index=1,
    horizontal=True,
    key=f"study_difficulty_{event.id}",
)
if st.button(f"Generate {QUIZ_SIZE} practice questions", type="primary"):
    generate(event, focus, difficulty)

render_quiz(event, focus, difficulty)
