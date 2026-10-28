import re

import streamlit as st

from bpa_app import llm
from bpa_app.data import (
    HelpAnswers,
    filter_events,
    keyword_search,
    load_events,
    match_answers,
    normalize_query,
)
from bpa_app.models import (
    DIVISIONS,
    EVENT_TYPES,
    FORMATS,
    PARTICIPATION,
    Event,
    SearchResult,
)
from bpa_app.ratelimit import check_and_count
from bpa_app.ui import AI_DISCLAIMER, DIVISION_LABELS, badges

CARDS_PER_ROW = 3
EXAMPLES = [
    "virtual team events for middle school",
    "events with certifications about coding",
    "individual speaking events for high school",
    "something creative with video for a team of 3",
]
_LIST_KEYS = ("f_formats", "f_participation", "f_types", "f_divisions", "f_subjects")
_TOGGLE_KEYS = ("f_cert", "f_presubmit")

TOP_PICKS = 5
INTEREST_KEYWORDS = ["coding", "design", "video", "finance", "healthcare", "speaking"]
NOT_INTERESTS = {"Virtual", "Middle School"}  # subjects that are really format/division
SOLO_OR_TEAM = {"Solo": "Individual", "Team": "Team", "Either is fine": None}
PREFERENCES = {
    "A test": "test",
    "A project": "project",
    "A presentation": "presentation",
    "A speech": "speech",
    "No preference": None,
}
WHERE = {"In person": "In-Person", "Virtual": "Virtual", "Either is fine": None}

Item = tuple[Event, str | None]  # an event and, for AI results, why it matches


def clear_filters() -> None:
    for key in _LIST_KEYS:
        st.session_state[key] = []
    for key in _TOGGLE_KEYS:
        st.session_state[key] = False
    st.session_state["nl_query"] = ""
    st.session_state.pop("nl_state", None)


def ask_ai() -> None:
    st.session_state["nl_pending"] = st.session_state.get("nl_query", "")


def use_example(example: str) -> None:
    st.session_state["nl_query"] = example
    st.session_state["nl_pending"] = example


@st.cache_data(ttl=86400, show_spinner=False)
def cached_nl_search(query_key: str) -> SearchResult:
    """Cached per normalized query; the rate limit is only charged on a cache miss."""
    allowed, message = check_and_count("search")
    if not allowed:
        raise llm.LLMError(message)
    return llm.nl_search(query_key, load_events())


def apply_filters(result: SearchResult) -> None:
    """Mirror the AI's interpretation in the sidebar widgets (before they render)."""
    f = result.filters
    st.session_state.update(
        f_formats=f.formats or [],
        f_participation=f.participation or [],
        f_types=f.event_types or [],
        f_divisions=f.divisions or [],
        f_subjects=f.subjects or [],
        f_cert=bool(f.certification_only),
        f_presubmit=bool(f.presubmit_only),
    )


def run_pending_search() -> None:
    query = normalize_query(st.session_state.pop("nl_pending", ""))
    if not query:
        return
    state: dict = {"query": query, "result": None, "error": None}
    with st.spinner("Asking the AI…"):
        try:
            state["result"] = cached_nl_search(query)
        except llm.LLMError as exc:
            state["error"] = str(exc)
        except RuntimeError:
            state["error"] = "AI search is not configured."
    if state["result"] is not None:
        apply_filters(state["result"])
    st.session_state["nl_state"] = state


def one_line_summary(event: Event, limit: int = 90) -> str:
    text = event.details.summary if event.details else event.subject
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def render_card(event: Event, reason: str | None = None, key_prefix: str = "") -> None:
    with st.container(border=True):
        st.caption(f"Event {event.id}")
        st.markdown(f"**{event.title}**")
        st.markdown(badges(event))
        st.caption(one_line_summary(event))
        if reason:
            st.markdown(f"💡 *{reason}*")
        if st.button("Details", key=f"{key_prefix}details_{event.id}", width="stretch"):
            st.switch_page("pages/event.py", query_params={"event": event.id})
        if event.view_url:
            st.link_button(
                "Official PDF",
                event.view_url,
                key=f"{key_prefix}pdf_{event.id}",
                width="stretch",
            )
        else:
            st.button(
                "Official PDF",
                key=f"{key_prefix}pdf_{event.id}",
                disabled=True,
                help="No PDF link available",
                width="stretch",
            )


def render_grid(items: list[Item], key_prefix: str = "") -> None:
    for start in range(0, len(items), CARDS_PER_ROW):
        row = items[start : start + CARDS_PER_ROW]
        for column, (event, reason) in zip(
            st.columns(CARDS_PER_ROW), row, strict=False
        ):
            with column:
                render_card(event, reason, key_prefix)


def interest_options(events: list[Event]) -> list[str]:
    taken = {k.casefold() for k in INTEREST_KEYWORDS}
    subjects = sorted({e.subject for e in events} - NOT_INTERESTS)
    return INTEREST_KEYWORDS + [s for s in subjects if s.casefold() not in taken]


def run_help_me_choose(answers: HelpAnswers) -> None:
    if answers.is_empty():
        st.session_state.pop("help_state", None)
        st.warning("Please answer at least one question.")
        return
    query = normalize_query(answers.to_query())
    state: dict = {"answers": answers, "result": None, "error": None}
    with st.spinner("Finding your best matches…"):
        try:
            state["result"] = cached_nl_search(query)
        except llm.LLMError as exc:
            state["error"] = str(exc)
        except RuntimeError:
            state["error"] = "AI search is not configured."
    st.session_state["help_state"] = state


def render_help_results() -> None:
    state = st.session_state.get("help_state")
    if not state:
        return
    by_answers = match_answers(events, state["answers"])
    ai_items: list[Item] = []
    if state["result"] is not None:
        result: SearchResult = state["result"]
        st.info(result.interpretation, icon="✨")
        st.caption(AI_DISCLAIMER)
        ai_items = [(events_by_id[h.id], h.reason) for h in result.results][:TOP_PICKS]
    else:
        st.caption(f"⚠️ {state['error']} Showing matches from your answers instead.")

    # The AI can be strict and return fewer than five; top up from the answers.
    chosen = {event.id for event, _ in ai_items}
    extra: list[Item] = [(e, None) for e in by_answers if e.id not in chosen][
        : TOP_PICKS - len(ai_items)
    ]
    if not ai_items and not extra:
        st.info("No events matched. Try loosening your answers.")
        return
    if ai_items:
        st.markdown(f"**Your top {len(ai_items) + len(extra)}**")
        render_grid(ai_items, key_prefix="help_")
        if extra:
            st.caption("More that fit your answers:")
    else:
        st.markdown(f"**Your top {len(extra)}**")
    render_grid(extra, key_prefix="help_")


def render_help_me_choose() -> None:
    with st.expander("🧭 Help me choose"):
        st.caption("Answer a few quick questions and the AI will suggest your top 5.")
        with st.form("help_me_choose"):
            division = st.radio(
                "1. Which division are you in?",
                list(DIVISIONS),
                format_func=DIVISION_LABELS.get,
                index=None,
                horizontal=True,
                key="hm_division",
            )
            team = st.radio(
                "2. Do you want to compete solo or on a team?",
                list(SOLO_OR_TEAM),
                index=2,
                horizontal=True,
                key="hm_team",
            )
            preference = st.radio(
                "3. What would you rather do?",
                list(PREFERENCES),
                index=4,
                horizontal=True,
                key="hm_preference",
            )
            interests = st.multiselect(
                "4. What are you interested in?",
                interest_options(events),
                placeholder="Pick any that apply",
                key="hm_interests",
            )
            where = st.radio(
                "5. Is in-person or virtual OK?",
                list(WHERE),
                index=2,
                horizontal=True,
                key="hm_where",
            )
            submitted = st.form_submit_button("Find my top 5", type="primary")
        if submitted:
            run_help_me_choose(
                HelpAnswers(
                    division=division,
                    participation=SOLO_OR_TEAM[team],
                    preference=PREFERENCES[preference],
                    interests=tuple(interests),
                    format=WHERE[where],
                )
            )
        render_help_results()


events = load_events()
events_by_id = {e.id: e for e in events}

st.title("🏆 BPA Event Explorer")

search_col, ask_col = st.columns([3, 1], vertical_alignment="center")
with search_col:
    query_text = st.text_input(
        "Describe what you're looking for…",
        key="nl_query",
        placeholder="Describe what you're looking for…",
        label_visibility="collapsed",
        max_chars=300,
    )
with ask_col:
    st.button(
        "✨ Ask AI",
        type="primary",
        on_click=ask_ai,
        disabled=not query_text.strip(),
        width="stretch",
    )
st.caption("Matches update when you press Enter. Click Ask AI for a smarter search.")

with st.container(horizontal=True):
    for i, example in enumerate(EXAMPLES):
        st.button(
            example,
            key=f"chip_{i}",
            on_click=use_example,
            args=(example,),
            width="content",
        )

render_help_me_choose()

# Must run before the sidebar widgets so the AI's filters can be written to them.
run_pending_search()
query = normalize_query(query_text)
state = st.session_state.get("nl_state")
ai = state if state and state["query"] == query else None

with st.sidebar:
    st.header("Filters")
    st.multiselect("Format", list(FORMATS), key="f_formats")
    st.multiselect("Individual / Team", list(PARTICIPATION), key="f_participation")
    st.multiselect("Testing / Judged", list(EVENT_TYPES), key="f_types")
    st.multiselect(
        "Division", list(DIVISIONS), format_func=DIVISION_LABELS.get, key="f_divisions"
    )
    st.multiselect("Subject", sorted({e.subject for e in events}), key="f_subjects")
    st.toggle("🏅 Certification only", key="f_cert")
    st.toggle("📤 Presubmit only", key="f_presubmit")
    st.button("Clear filters", on_click=clear_filters, width="stretch")

filtered = filter_events(
    events,
    formats=st.session_state.get("f_formats"),
    participation=st.session_state.get("f_participation"),
    event_types=st.session_state.get("f_types"),
    divisions=st.session_state.get("f_divisions"),
    subjects=st.session_state.get("f_subjects"),
    certification_only=st.session_state.get("f_cert", False),
    presubmit_only=st.session_state.get("f_presubmit", False),
)

items: list[Item]
if ai and ai["result"] is not None:
    result: SearchResult = ai["result"]
    st.info(result.interpretation, icon="✨")
    st.caption(AI_DISCLAIMER)
    allowed = {e.id for e in filtered}
    items = [(events_by_id[h.id], h.reason) for h in result.results if h.id in allowed]
    st.markdown(f"**{len(items)}** AI matches")
elif query:
    if ai and ai["error"]:
        st.caption(f"⚠️ {ai['error']} Showing keyword results instead.")
    items = [(e, None) for e in keyword_search(filtered, query)]
    st.markdown(f"**{len(items)}** keyword matches")
else:
    items = [(e, None) for e in filtered]
    st.markdown(f"**{len(items)}** of {len(events)} events")

if not items:
    st.info("No events match. Try different words or clear the filters.")
render_grid(items)
