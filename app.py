import streamlit as st
from pydantic import ValidationError

from bpa_app.data import load_events

st.set_page_config(page_title="BPA Event Explorer", page_icon="🏆", layout="wide")

try:
    load_events()
except (OSError, ValidationError, ValueError):
    st.title("🏆 BPA Event Explorer")
    st.error(
        "The event data isn't available right now. Please try again later, or let "
        "the site owner know."
    )
    st.stop()

pages = [
    st.Page("pages/browse.py", title="Browse events", icon="🔎", default=True),
    st.Page("pages/event.py", title="Event details", icon="📄", url_path="event"),
    st.Page("pages/evaluate.py", title="Evaluate", icon="📝"),
    st.Page("pages/study.py", title="Study", icon="📚"),
    st.Page("pages/compare.py", title="Compare", icon="⚖️"),
    st.Page("pages/about.py", title="About", icon="ℹ️"),
]

st.navigation(pages).run()
