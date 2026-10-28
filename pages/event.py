from collections.abc import Callable, Iterator

import streamlit as st

from bpa_app import config, llm
from bpa_app.data import get_event, load_event_text, load_events
from bpa_app.models import Event
from bpa_app.prompts import event_qa_system, event_qa_user_prompt
from bpa_app.ratelimit import check_and_count
from bpa_app.ui import (
    AI_DISCLAIMER,
    badges,
    checklist_markdown,
    escape_md,
    rubric_dataframe,
    team_size_text,
)

SUGGESTED_QUESTIONS = [
    "How is this event scored?",
    "What do I need to submit and when?",
    "What are common penalties?",
    "How long is the presentation?",
]
HISTORY_MESSAGES = 6  # last 3 question/answer pairs go back to the model
NOT_STATED = "Not stated in the guidelines."
NO_DETAILS = (
    "Detailed information hasn't been extracted for this event yet. "
    "Please check the official PDF."
)


def back_to_browse(key: str) -> None:
    if st.button("⬅️ Back to browse", key=key):
        st.switch_page("pages/browse.py")


def select_event() -> Event:
    """Use ?event=<id>, falling back to a picker; stops the page if none is chosen."""
    event_id = st.query_params.get("event", "")
    event = get_event(event_id) if event_id else None
    if event is not None:
        return event

    st.title("Event details")
    if event_id:
        st.warning(f"No event with id “{event_id}”. Pick one below.")
    options = {f"{e.id} – {e.title}": e.id for e in load_events()}
    choice = st.selectbox(
        "Choose an event",
        list(options),
        index=None,
        placeholder="Search by id or title",
    )
    back_to_browse("back_picker")
    if choice is None:
        st.stop()
    st.query_params["event"] = options[choice]
    st.rerun()


def bullets(items: list[str], empty: str = NOT_STATED) -> None:
    if items:
        st.markdown("\n".join(f"- {escape_md(item)}" for item in items))
    else:
        st.caption(empty)


def render_header(event: Event) -> None:
    back_to_browse("back_header")
    st.title(event.title)
    st.caption(f"Event {event.id} · {event.subject}")
    st.markdown(badges(event))
    if event.view_url:
        st.link_button("Official PDF", event.view_url, key="pdf_header")


def render_overview(event: Event) -> None:
    details = event.details
    if details is None:
        st.info(NO_DETAILS)
        return
    st.markdown(escape_md(details.summary))
    st.metric("Team size", team_size_text(event))

    st.subheader("Time limits")
    bullets(details.time_limits)

    st.subheader("Deadlines")
    deadlines = list(details.deadlines)
    if event.regional_deadline:
        deadlines.append(f"Regional submission deadline: {event.regional_deadline}")
    if event.nlc_deadline:
        deadlines.append(f"NLC presubmit deadline: {event.nlc_deadline}")
    bullets(deadlines)

    st.subheader("Eligibility")
    bullets(details.eligibility_notes)


def render_checklist(event: Event) -> None:
    details = event.details
    if details is None:
        st.info(NO_DETAILS)
        return
    sections = {
        "What to submit": details.submission_requirements,
        "Pre-submit items": details.presubmit_items,
        "What to bring": details.what_to_bring,
    }
    if not any(sections.values()):
        st.caption(NOT_STATED)
        return

    # Own session dict so ticks survive leaving the page, which drops widget state.
    done = st.session_state.setdefault("checklist", {}).setdefault(event.id, {})
    for name, items in sections.items():
        if not items:
            continue
        st.subheader(name)
        for index, item in enumerate(items):
            key = f"{name}-{index}"
            done[key] = st.checkbox(
                escape_md(item), value=done.get(key, False), key=f"chk_{event.id}_{key}"
            )

    total = sum(len(items) for items in sections.values())
    st.caption(f"{sum(done.values())} of {total} done")
    st.download_button(
        "Download checklist",
        checklist_markdown(event, sections, done),
        file_name=f"checklist_{event.id}.md",
        mime="text/markdown",
    )


def render_rubric(event: Event) -> None:
    details = event.details
    if details is None:
        st.info(NO_DETAILS)
        return

    if not details.rubric:
        if event.event_type == ["Testing"]:
            st.info("This is a testing event – see Competencies.")
        else:
            st.info("No scoring rubric was found in the guidelines.")
        st.subheader("Competencies")
        bullets(details.competencies)
        if (
            "Testing" in event.event_type
            and details.competencies
            and st.button("Practice questions", key="to_study")
        ):
            st.switch_page("pages/study.py", query_params={"event": event.id})
        return

    st.dataframe(
        rubric_dataframe(details.rubric),
        hide_index=True,
        width="stretch",
        column_config={"Max points": st.column_config.NumberColumn(format="%g")},
    )
    if st.button("Practice with this rubric", key="to_evaluate"):
        st.switch_page("pages/evaluate.py", query_params={"event": event.id})

    listed = sum(i.max_points for i in details.rubric if i.max_points is not None)
    stated = [(s.section, s.total_points) for s in details.rubric_section_totals]
    if details.rubric_total_points is not None:
        st.metric("Total points", f"{details.rubric_total_points:g}")
    for section, points in stated:
        st.metric(section, f"{points:g} points")
    if details.rubric_total_points is None and not stated:
        st.caption(
            f"Total not stated in the guidelines; listed items add up to {listed:g}."
        )

    st.subheader("Judging notes")
    bullets(details.judging_notes)


def clear_chat(event_id: str) -> None:
    st.session_state.setdefault("chats", {})[event_id] = []


def stream_answer(
    system: str, prompt: str, raw_chunks: list[str], on_first_chunk: Callable[[], None]
) -> Iterator[str]:
    for chunk in llm.stream_text(prompt, system=system, model=config.MODEL_FAST):
        if not raw_chunks:
            on_first_chunk()
        raw_chunks.append(chunk)
        yield escape_md(chunk)


def answer_question(event: Event, guideline: str, question: str, history: list) -> None:
    """Show the question and streamed answer, then record both on success."""
    with st.chat_message("user"):
        st.markdown(escape_md(question))
    with st.chat_message("assistant"):
        allowed, message = check_and_count("chat")
        if not allowed:
            st.warning(message)
            return
        thinking = st.empty()
        thinking.caption("Looking through the guidelines…")
        raw_chunks: list[str] = []
        try:
            st.write_stream(
                stream_answer(
                    event_qa_system(event, guideline),
                    event_qa_user_prompt(history[-HISTORY_MESSAGES:], question),
                    raw_chunks,
                    thinking.empty,
                )
            )
        except llm.LLMError as exc:
            thinking.empty()
            st.error(str(exc))
            return
        except RuntimeError:
            thinking.empty()
            st.error("AI Q&A is not configured.")
            return
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": "".join(raw_chunks)})


def render_chat(event: Event) -> None:
    guideline = load_event_text(event.id)
    history: list = st.session_state.setdefault("chats", {}).setdefault(event.id, [])

    if guideline is None:
        st.info(
            "The guideline text for this event isn't available yet, so questions "
            "can't be answered. Please check the official PDF."
        )
    else:
        suggested: str | None = None
        with st.container(horizontal=True):
            for index, text in enumerate(SUGGESTED_QUESTIONS):
                if st.button(text, key=f"suggest_{event.id}_{index}"):
                    suggested = text
            if history:
                st.button(
                    "Clear chat",
                    key=f"clear_{event.id}",
                    on_click=clear_chat,
                    args=(event.id,),
                )
        messages = st.container()
        typed = st.chat_input(
            "Ask about this event…", key=f"chat_input_{event.id}", max_chars=500
        )
        question = typed or suggested
        with messages:
            for message in history:
                with st.chat_message(message["role"]):
                    st.markdown(escape_md(message["content"]))
            if question:
                answer_question(event, guideline, question, history)

    st.caption(AI_DISCLAIMER)
    if event.view_url:
        st.link_button(
            "Open the official guideline (PDF)", event.view_url, key="pdf_chat"
        )


event = select_event()
render_header(event)

overview_tab, checklist_tab, rubric_tab, ask_tab = st.tabs(
    ["Overview", "Requirements & Checklist", "Rubric", "Ask a question"]
)
with overview_tab:
    render_overview(event)
with checklist_tab:
    render_checklist(event)
with rubric_tab:
    render_rubric(event)
with ask_tab:
    render_chat(event)
