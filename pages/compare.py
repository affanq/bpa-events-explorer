import streamlit as st

from bpa_app.data import get_event, load_events
from bpa_app.ui import (
    COMPARE_FIELDS,
    NOT_AVAILABLE,
    NOT_STATED,
    escape_md,
)

MIN_EVENTS = 2
MAX_EVENTS = 4
TAG_CSS = """
<style>
.cmp-tag { display: none; font-size: 0.8rem; font-weight: 600; color: #003366; }
@media (max-width: 640px) { .cmp-tag { display: inline-block; } }
</style>
"""
QUICK_PICKS = {
    "Graphic Design": ["410", "945"],
    "Video": ["430", "950"],
    "Website": ["365", "955", "V04"],
    "Visual Design": ["460", "960"],
    "Speech": ["735", "755", "975", "980"],
    "Interview": ["725", "730", "V15"],
}

events = load_events()
by_id = {e.id: e for e in events}


def option_label(event_id: str) -> str:
    # Several events share a title across divisions, so the division tells them apart.
    event = by_id[event_id]
    return f"{event.id} – {event.title} · {'/'.join(event.divisions)}"


def pick(event_ids: list[str]) -> None:
    st.session_state["compare_ids"] = [i for i in event_ids if i in by_id][:MAX_EVENTS]


def render_values(event_id: str, lines: list[str]) -> None:
    # On phones the columns stack, so each cell names its event (hidden on wide screens).
    st.markdown(
        f'<span class="cmp-tag">Event {event_id}</span>', unsafe_allow_html=True
    )
    if len(lines) == 1:
        line = lines[0]
        if line in (NOT_STATED, NOT_AVAILABLE):
            st.caption(line)
        else:
            st.markdown(escape_md(line))
    else:
        st.markdown("\n".join(f"- {escape_md(line)}" for line in lines))


st.title("Compare events")

if "compare_ids" not in st.session_state:
    requested = st.query_params.get("event", "")
    st.session_state["compare_ids"] = [requested] if get_event(requested) else []

st.multiselect(
    f"Events to compare ({MIN_EVENTS}–{MAX_EVENTS})",
    list(by_id),
    format_func=option_label,
    max_selections=MAX_EVENTS,
    key="compare_ids",
    placeholder="Search by id or title",
)

st.caption("Quick picks")
with st.container(horizontal=True):
    for name, ids in QUICK_PICKS.items():
        st.button(
            name,
            key=f"pick_{name}",
            on_click=pick,
            args=(ids,),
            help=", ".join(ids),
        )

selected = [by_id[i] for i in st.session_state["compare_ids"] if i in by_id]
if len(selected) < MIN_EVENTS:
    st.info(f"Choose at least {MIN_EVENTS} events (up to {MAX_EVENTS}) to compare.")
    st.stop()

header_cols = st.columns(len(selected))
for column, event in zip(header_cols, selected, strict=True):
    with column:
        st.markdown(f"**{escape_md(event.title)}**")
        st.caption(f"Event {event.id} · {'/'.join(event.divisions)}")
        if st.button("Details", key=f"cmp_details_{event.id}", width="stretch"):
            st.switch_page("pages/event.py", query_params={"event": event.id})

st.markdown(TAG_CSS, unsafe_allow_html=True)
for field, values in COMPARE_FIELDS.items():
    st.markdown(f":blue[**{field}**]")
    for column, event in zip(st.columns(len(selected)), selected, strict=True):
        with column:
            render_values(event.id, values(event))
