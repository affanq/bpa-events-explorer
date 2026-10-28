import streamlit as st

from bpa_app import config
from bpa_app.data import load_events
from bpa_app.ui import (
    AI_DISCLAIMER,
    BPA_WEBSITE,
    GUIDELINES_RELEASE,
    PRACTICE_DISCLAIMER,
    QUIZ_DISCLAIMER,
    guideline_links_dataframe,
    provider_name,
    report_error_link,
)

events = load_events()

st.title("About BPA Event Explorer")
st.warning(
    "**This is not an official BPA product.** It is an independent, free tool for "
    "students and advisors, and it is not made, endorsed or supported by Business "
    "Professionals of America. The official guidelines always come first.",
    icon="⚠️",
)

st.header("What this app does")
st.markdown(
    f"""
- **Browse events:** filter all {len(events)} competitive events, search in plain
  language, or answer a few questions to get suggestions.
- **Event details:** a summary, time limits, deadlines, a checklist, the scoring rubric,
  and a chat that answers questions from the event's guideline.
- **Evaluate:** get practice feedback on a draft, scored against the event's rubric.
- **Study:** practice questions for testing events.
- **Compare:** put 2–4 events side by side.
"""
)

st.header("Where the data comes from")
st.markdown(
    f"""
Everything comes from the official BPA Workplace Skills Assessment Program
**2026-2027** guidelines ({GUIDELINES_RELEASE}) and BPA's event list. The details shown
for each event, such as the summary, rubric and checklist, were read from those
guideline PDFs automatically, so a few may be wrong or out of date. Find BPA itself at
[{BPA_WEBSITE.removeprefix("https://")}]({BPA_WEBSITE}).
"""
)
with st.expander("Official guideline PDFs"):
    st.caption("Every event page also has a link to its official PDF.")
    st.dataframe(
        guideline_links_dataframe(events),
        hide_index=True,
        width="stretch",
        column_config={
            "Official PDF": st.column_config.LinkColumn(
                "Official PDF", display_text="Open PDF"
            )
        },
    )

st.header("AI features")
st.info(AI_DISCLAIMER, icon="🤖")
st.markdown(
    f"""
- Search suggestions, event answers, feedback and practice questions are written by AI
  and can be wrong or incomplete. Check anything important in the official guideline.
- {PRACTICE_DISCLAIMER}
- {QUIZ_DISCLAIMER}
- To keep the app free for everyone, each visitor gets a limited number of AI requests
  per hour, and the whole app has a daily limit.
"""
)

st.header("Privacy")
st.markdown(
    f"""
- **Uploads are not stored.** Files and pasted text are read in memory, sent to
  **{provider_name()}** for analysis, and discarded. This app saves no uploads and no
  chat history, and keeps no accounts.
- **Please don't include personal information** such as names, emails, phone numbers or
  your school in anything you upload or type.
- Your questions and drafts are not written to any log by this app. The AI provider
  handles what it receives under its own terms.
"""
)

st.header("Report a data error")
st.write(
    "Spotted a wrong date, point value or requirement? Tell us the event number and "
    "what looks wrong, and include the page of the official PDF if you can."
)
st.link_button("Report a data error", report_error_link(), icon="✉️")
if config.REPORT_EMAIL == config.PLACEHOLDER_REPORT_EMAIL:
    st.caption("The contact address isn't set up yet. Set REPORT_EMAIL to enable this.")
