# Copilot Instructions – BPA Event Explorer

## Purpose
A small, free, information-only web app for Business Professionals of America (BPA) students and advisors. Users can:
1. Browse and filter the 113 BPA competitive events for 2026-2027.
2. Search events in natural language ("virtual team events for middle school involving video").
3. Ask questions about a specific event (rubric, submission requirements, time limits) answered ONLY from that event's official guideline PDF.
4. Get practice feedback on a draft submission scored against the event rubric.
5. Generate practice questions for testing events.

Expected users: ≤100. Cost target: $0 (Gemini free tier, Streamlit Community Cloud). Simplicity beats cleverness.

## Tech stack (do not add other frameworks without asking)
- Python 3.11+, managed with **uv** (`uv add <pkg>`, `uv run <cmd>`). Never use pip directly.
- **Streamlit** for the UI (multipage via `st.navigation` / `st.Page`).
- **google-genai** SDK (`from google import genai`) for Gemini. Do NOT use the deprecated `google-generativeai` package.
- **pydantic v2** for all data models and Gemini structured output schemas.
- **pandas + openpyxl** for reading the Excel file.
- **PyMuPDF** (`import pymupdf`) for PDF text extraction.
- **python-docx**, **python-pptx** for reading uploaded submissions.
- **pytest** for tests, **ruff** for lint/format.
- No database, no vector store, no LangChain/LlamaIndex. Data lives in JSON/Markdown files committed to the repo.

## Project layout
```
.
├── .github/copilot-instructions.md
├── .streamlit/
│   ├── config.toml              # theme
│   └── secrets.toml             # GEMINI_API_KEY (gitignored)
├── data/
│   ├── *.pdf                    # downloaded guideline PDFs (gitignored), e.g. 430_Video_Production_Team.pdf
│   ├── source/
│   │   ├── BPA Event Requirements 2026-2027.xlsx
│   │   └── bpa_event_pdf_links.csv
│   └── processed/               # GENERATED – committed, the app reads only this
│       ├── catalog.json         # step 1 output (from Excel + CSV)
│       ├── text/{event_id}.md   # step 2 output (full PDF text)
│       ├── details/{event_id}.json  # step 3 output (AI-extracted structured details)
│       └── events.json          # final merged file used by the app
├── scripts/
│   ├── build_catalog.py         # Excel + CSV -> catalog.json
│   ├── extract_text.py          # PDFs -> text/*.md
│   ├── extract_details.py       # PDFs -> details/*.json via Gemini
│   ├── merge_events.py          # catalog + details -> events.json
│   └── validate_data.py         # report gaps / problems
├── bpa_app/                     # importable package
│   ├── __init__.py
│   ├── config.py                # paths, model names, limits, get_api_key()
│   ├── models.py                # pydantic models (Event, EventDetails, RubricItem, ...)
│   ├── data.py                  # load events, filtering, keyword search
│   ├── llm.py                   # ALL LLM calls live here (Cortex or Gemini)
│   ├── prompts.py               # ALL prompt templates live here
│   ├── documents.py             # read uploaded PDF/DOCX/PPTX/TXT
│   └── ratelimit.py             # simple per-session + global daily limits
├── app.py                       # Streamlit entry point (navigation only)
├── pages/
│   ├── browse.py                # filters + natural language search
│   ├── event.py                 # event detail + Q&A chat
│   ├── evaluate.py              # submission feedback
│   ├── study.py                 # practice questions
│   ├── compare.py               # side-by-side comparison
│   └── about.py                 # disclaimer, data source, privacy
├── tests/
├── pyproject.toml
└── requirements.txt             # exported from uv for Streamlit Cloud
```

## Source data facts (IMPORTANT – the Excel is messy)
Workbook `BPA Event Requirements 2026-2027.xlsx` has 3 sheets. Ignore fully empty rows (there are hundreds).

**Sheet `IndividualTeam`** (82 events) columns:
`Event #, Subject, Title, Individual or Team, Type, Certification, Presubmit, Division, Regional Submission Deadline, NLC Presubmit Deadline`

**Sheet `Virtual`** (16 events) columns:
`Event #, Title, Type, Registration Deadline, Certification, Presubmit, Presubmit Deadline, Division`
- Here `Type` actually means Individual/Team (NOT Testing/Judged).
- No `Subject` column. Certification/Presubmit/deadlines are blank.
- Event IDs are strings like `V01`; `"V15 "` has a trailing space.

**Sheet `Open Events`** (15 events) columns:
`Event #, Subject, Title, Individual or Team, Type, Division`
- `490` has typo `IndividuaI` (capital i) → treat as `Individual`.
- `190` has no PDF link.

**Normalization rules**
- Strip whitespace from every string cell. Event IDs are strings (`"100"`, `"V01"`).
- Division → list of codes from {`MS`, `HS`, `College`}:
  - `High School`, `Highschool` → `["HS"]`
  - `College` → `["College"]`
  - `High School/College`, `Highschool/College` → `["HS","College"]`
  - `Middle School` → `["MS"]`
  - `College/HS/MS` → `["MS","HS","College"]`
  - Anything unrecognized → raise a clear error naming the event.
- Type → list from {`Testing`, `Judged`}: `"Testing "` → `["Testing"]`; `Testing/Judged` → `["Testing","Judged"]`.
- Participation → `Individual` | `Team` (fix `IndividuaI`).
- Format → `In-Person` (IndividualTeam sheet), `Virtual` (Virtual sheet), `Open` (Open Events sheet).
- Certification / Presubmit → bool; Excel may give real booleans or strings `"TRUE"/"FALSE"`; blank → `None` (unknown).
- Virtual events: subject = `"Virtual"`; event_type defaults to `["Judged"]` (project-based) unless PDF extraction says otherwise.
- Deadlines: currently blank in Excel → `None`; may be filled from PDF extraction.
- PDF links come from `bpa_event_pdf_links.csv` (columns `Sheet, Event #, Title, File ID, View URL, Direct Download URL`), joined on `Event #` (trimmed).
- Local PDFs are named `{event_id}_{Title_with_underscores}.pdf`; match on the prefix before the first `_`.

## Data model (final `events.json` – list of Event)
```python
class RubricItem(BaseModel):
    section: str | None          # name of the scoring rubric/table, e.g. "Presentation Rubric"
    criterion: str
    max_points: float | None
    description: str | None      # what earns high marks, if stated

class SectionTotal(BaseModel):
    section: str                 # must equal the `section` used on its RubricItems
    total_points: float          # total stated in the document for that rubric

class EventDetails(BaseModel):   # extracted by Gemini from the PDF
    summary: str                 # 2–3 plain-language sentences for students
    team_size_min: int | None
    team_size_max: int | None
    time_limits: list[str]       # e.g. "Presentation: 7 minutes", "Test: 60 minutes"
    submission_requirements: list[str]   # what must be submitted / produced
    presubmit_items: list[str]
    deadlines: list[str]         # as written in the PDF
    what_to_bring: list[str]
    competencies: list[str]      # skills/topics assessed (key for testing events)
    rubric: list[RubricItem]
    rubric_total_points: float | None    # one total over all items, only if stated
    rubric_section_totals: list[SectionTotal] = []
    judging_notes: list[str]     # penalties, disqualifications, tie-breakers
    eligibility_notes: list[str]
    keywords: list[str]          # 5–10 search terms

class Event(BaseModel):
    id: str
    title: str
    subject: str
    format: Literal["In-Person", "Virtual", "Open"]
    participation: Literal["Individual", "Team"]
    event_type: list[Literal["Testing", "Judged"]]
    divisions: list[Literal["MS", "HS", "College"]]
    certification: bool | None
    presubmit: bool | None
    regional_deadline: str | None
    nlc_deadline: str | None
    view_url: str | None
    download_url: str | None
    pdf_file: str | None         # local filename, if downloaded
    has_text: bool
    details: EventDetails | None
```

## LLM usage rules
- Two providers behind one interface, chosen by `LLM_PROVIDER`: `cortex` (private network, for testing) or `gemini` (default; public deployment). Switching needs no code changes.
- All API calls go through `bpa_app/llm.py` (`generate_text`, `stream_text`, `generate_structured`); all prompt text lives in `bpa_app/prompts.py`. Never import `google.genai` or call Cortex elsewhere.
- API key: `get_api_key()` returns `CORTEX_TOKEN` or `GEMINI_API_KEY` for the active provider, from `.env`/environment (scripts) then `st.secrets` (app). Never hardcode or log keys.
- Model names come from `config.py` (overridable with `LLM_MODEL_FAST` / `LLM_MODEL_SMART`):
  - Gemini: `gemini-3.5-flash-lite` (fast: search, Q&A, quiz), `gemini-3.8-flash` (smart: extraction, evaluation); the 2.5 models return 404 for new API keys
  - Cortex: `gpt-4.1-2025-04-14-us-data-zone` for both tiers
- Cortex differences: no streaming (`stream_text` yields one chunk), no PDF input (`llm.supports_pdf()` is False, so send extracted text from `data/processed/text/`), JSON schema is passed in the prompt, requires the `CORTEX_USE_CASE` header, `CORTEX_API_BASE_URL` (no default) and, on a corporate network, a CA bundle (`CORTEX_CA_BUNDLE`).
- Use `generate_structured(prompt, Schema)` whenever the response is consumed by code; it validates with pydantic and raises `LLMError` on a bad format.
- `llm.py` retries 429/5xx with exponential backoff (max 3). Catch `LLMError` and show its message in a friendly Streamlit message. The app must never crash on an LLM error.
- Grounding: answers about an event must use only that event's text. If the answer isn't in the document, say so and suggest checking with the chapter advisor or the official BPA guidelines.
- Always show a link to the official PDF (`view_url`) next to AI answers.

## UI conventions
- Load data once with `@st.cache_data`. LLM clients are created once inside `llm.py`.
- Use `st.session_state` for chat history (keyed by event id) and the selected event.
- Pass the selected event between pages via `st.query_params["event"]` so event pages can be linked to.
- Badges/labels: Format, Individual/Team, Testing/Judged, divisions, 🏅 Certification, 📤 Presubmit.
- Keep a visible disclaimer on AI features: "AI-generated – may contain errors. Always check the official guidelines."
- Mobile-friendly: avoid very wide tables; prefer `st.container(border=True)` cards.

## Privacy & safety (users include minors)
- Never store uploaded files or chat contents on disk; process in memory only.
- Do not log user text. Log only counts/errors.
- Upload limit 10 MB; accepted types: pdf, docx, pptx, txt, md.
- Show a notice on the Evaluate page that the content is sent to the AI provider (Google Gemini in the public app) for analysis.

## Coding conventions
- Type hints everywhere; pydantic models over dicts.
- Small, pure functions in `bpa_app/`; Streamlit pages stay thin.
- `pathlib.Path` for all paths, defined in `config.py` relative to the repo root.
- Scripts are idempotent: skip work whose output already exists unless `--force`.
- Scripts print a short summary at the end (counts, failures).
- Write pytest tests for normalization, filtering and keyword search (no network in tests; mock `llm.py`).
- Run `uv run ruff check --fix . && uv run ruff format .` before finishing a task.

## Don'ts
- Don't add a database, auth system, vector DB or background workers.
- Don't fetch PDFs from Google Drive at runtime.
- Don't invent event facts in code or prompts; data comes from the files.
- Don't commit `data/*.pdf`, `.env` or `.streamlit/secrets.toml`.
