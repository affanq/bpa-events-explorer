import streamlit as st

from bpa_app import config, llm
from bpa_app.data import get_event, load_events, rubric_sections, select_rubric
from bpa_app.documents import SUPPORTED_TYPES, UploadError, read_upload
from bpa_app.models import Evaluation, Event
from bpa_app.prompts import MAX_NOTES_CHARS
from bpa_app.ratelimit import check_and_count
from bpa_app.ui import (
    AI_DISCLAIMER,
    PRACTICE_DISCLAIMER,
    badges,
    escape_md,
    feedback_markdown,
    provider_name,
    rubric_dataframe,
    score_label,
    score_percent,
)

LABEL_CHARS = 90


def choose_event(events: list[Event]) -> Event:
    """Pick from events with a rubric; defaults to ?event=<id> when it qualifies."""
    requested = st.query_params.get("event", "")
    index = next((i for i, e in enumerate(events) if e.id == requested), None)
    if index is None and requested and get_event(requested) is not None:
        st.info(
            f"Event {requested} has no scoring rubric, so it can't be evaluated. "
            "Please choose another event."
        )
    options = {f"{e.id} – {e.title}": e for e in events}
    choice = st.selectbox(
        "Event to be scored against",
        list(options),
        index=index,
        placeholder="Choose an event",
    )
    if choice is None:
        st.stop()
    event = options[choice]
    st.query_params["event"] = event.id
    return event


def choose_sections(event: Event) -> list[str]:
    sections = rubric_sections(event.details)
    if len(sections) == 1:
        return sections
    return st.multiselect(
        "Rubric(s) to score",
        sections,
        default=sections[:1],
        key=f"eval_sections_{event.id}",
        help="Some events have separate rubrics, for example technical and presentation.",
    )


def submit(
    event: Event, uploaded, pasted: str, notes: str, sections: list[str]
) -> None:
    if not uploaded and not pasted.strip():
        st.warning("Please upload a file or paste your text first.")
        return
    try:
        text, pdf = read_upload(uploaded) if uploaded else (pasted.strip(), None)
    except UploadError as exc:
        st.error(str(exc))
        return
    if not text and not (pdf and llm.supports_pdf()):
        st.error("No readable text was found. Please paste your text instead.")
        return

    allowed, message = check_and_count("evaluation")
    if not allowed:
        st.warning(message)
        return
    with st.spinner("Judging your draft… this can take up to a minute."):
        try:
            result = llm.evaluate_submission(event, text, pdf, notes.strip(), sections)
        except llm.LLMError as exc:
            st.error(str(exc))
            return
        except RuntimeError:
            st.error("AI evaluation is not configured.")
            return
    # Only the feedback is kept in the session, never the submission itself.
    st.session_state["evaluation"] = {"event_id": event.id, "result": result}


def render_result(event: Event, result: Evaluation) -> None:
    st.divider()
    st.subheader("Your practice feedback")
    st.warning(PRACTICE_DISCLAIMER, icon="⚠️")
    st.caption(AI_DISCLAIMER)

    if result.max_total > 0:
        score_col, bar_col = st.columns([1, 2], vertical_alignment="center")
        score_col.metric(
            "Estimated score", f"{result.estimated_total:g} / {result.max_total:g}"
        )
        percent = score_percent(result)
        bar_col.progress(
            min(percent / 100, 1.0),
            text=f"{percent:.0f}% of the points that could be assessed",
        )
    else:
        st.info("No points could be estimated from this draft.")
    if result.cannot_assess:
        items = "\n".join(f"- {escape_md(item)}" for item in result.cannot_assess)
        st.info(f"**Not scored – can't be judged from a document:**\n{items}")

    if result.criteria:
        st.subheader("Criteria")
    for criterion in result.criteria:
        name = criterion.criterion
        short = name if len(name) <= LABEL_CHARS else name[: LABEL_CHARS - 1] + "…"
        with st.expander(f"{escape_md(short)} — {score_label(criterion)}"):
            if short != name:
                st.markdown(f"**Criterion:** {escape_md(name)}")
            st.markdown(f"**Evidence:** {escape_md(criterion.evidence)}")
            st.markdown(f"**How to improve:** {escape_md(criterion.suggestions)}")

    st.subheader("Missing requirements")
    if result.missing_requirements:
        for item in result.missing_requirements:
            st.warning(escape_md(item))
    else:
        st.success("No missing requirements found.")

    if result.top_3_improvements:
        st.subheader("Top 3 improvements")
        st.markdown(
            "\n".join(
                f"{n}. {escape_md(item)}"
                for n, item in enumerate(result.top_3_improvements, start=1)
            )
        )
    if result.strengths:
        st.subheader("What you did well")
        st.markdown("\n".join(f"- {escape_md(item)}" for item in result.strengths))

    st.download_button(
        "Download feedback (.md)",
        feedback_markdown(event, result),
        file_name=f"feedback_{event.id}.md",
        mime="text/markdown",
    )


st.title("Evaluate a submission")
st.warning(PRACTICE_DISCLAIMER, icon="⚠️")
st.info(
    f"🔒 Your draft and notes are sent to {provider_name()} for analysis and are not "
    "stored by this app. Please don't upload personal information such as names, "
    "emails, phone numbers or your school.",
)

events = [e for e in load_events() if e.details and e.details.rubric]
if not events:
    st.info("No events with a scoring rubric are available yet.")
    st.stop()

event = choose_event(events)
st.markdown(badges(event))
sections = choose_sections(event)
with st.expander("What will be assessed", expanded=True):
    if sections:
        st.dataframe(
            rubric_dataframe(select_rubric(event.details, sections)),
            hide_index=True,
            width="stretch",
            column_config={"Max points": st.column_config.NumberColumn(format="%g")},
        )
    else:
        st.caption("Choose at least one rubric.")

uploaded = st.file_uploader(
    "Upload your draft (PDF, Word, PowerPoint or text)",
    type=list(SUPPORTED_TYPES),
    key=f"eval_file_{event.id}",
)
pasted = st.text_area(
    "Or paste your text",
    height=200,
    max_chars=config.MAX_UPLOAD_TEXT_CHARS,
    placeholder="Paste your script, outline or written content here…",
    key=f"eval_text_{event.id}",
)
if uploaded and pasted.strip():
    st.caption("The uploaded file will be used; the pasted text is ignored.")
notes = st.text_area(
    "Anything the judge should know? (optional)",
    height=80,
    max_chars=MAX_NOTES_CHARS,
    placeholder='e.g. "This is our script; the video is submitted separately."',
    key=f"eval_notes_{event.id}",
)

if st.button("Evaluate my draft", type="primary", disabled=not sections):
    submit(event, uploaded, pasted, notes, sections)

state = st.session_state.get("evaluation")
if state and state["event_id"] == event.id:
    render_result(event, state["result"])
