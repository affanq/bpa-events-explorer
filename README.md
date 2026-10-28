# BPA Event Explorer

A small, free, information-only web app for Business Professionals of America (BPA) students and advisors. It covers the 113 competitive events for 2026-2027 and lets users:

- browse and filter events, or search in plain language ("virtual team events for middle school involving video");
- ask questions about one event, answered only from its official guideline PDF;
- get practice feedback on a draft submission, scored against the event rubric;
- generate practice questions for testing events;
- compare events side by side.

AI answers can contain errors. The app always links to the official guidelines. It is not affiliated with BPA.

## Screenshots

<!-- TODO: add screenshots (Browse, Event chat, Evaluate, Study) under docs/ and link them here. -->

| Browse | Event Q&A |
| --- | --- |
| _placeholder_ | _placeholder_ |

| Evaluate | Study |
| --- | --- |
| _placeholder_ | _placeholder_ |

## Local setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer (`.python-version` pins 3.13).

```bash
uv sync
uv run streamlit run app.py
```

Create `.env` (never committed) before running the AI features:

```dotenv
GEMINI_API_KEY=your-key-from-google-ai-studio
# LLM_PROVIDER=gemini       # default
# REPORT_EMAIL=you@example.com
```

Get a free key at <https://aistudio.google.com/apikey>.

Checks:

```bash
uv run ruff check --fix . && uv run ruff format .
uv run pytest
uv run python scripts/smoke_gemini.py   # calls the real Gemini API for every AI feature
```

The app reads only `data/processed/`, which is committed, so it runs without the PDFs.

## Refresh the data each season

Inputs live in `data/source/` (the event Excel workbook and `bpa_event_pdf_links.csv`). Guideline PDFs go in `data/pdfs/`, which is gitignored.

1. Replace the files in `data/source/` with the new season's versions.
2. Download the PDFs (skips files already present; failures go to `download_failures.csv`):

   ```bash
   uv run --with requests python download_bpa_pdfs.py \
     --csv data/source/bpa_event_pdf_links.csv --out data/pdfs
   ```

3. Run the four scripts in order. Each skips work whose output already exists; add `--force` to redo it.

   ```bash
   uv run python scripts/build_catalog.py     # Excel + CSV -> data/processed/catalog.json
   uv run python scripts/extract_text.py      # PDFs -> data/processed/text/{id}.md
   uv run python scripts/extract_details.py   # PDFs -> data/processed/details/{id}.json (uses the AI provider)
   uv run python scripts/merge_events.py      # catalog + details -> data/processed/events.json
   ```

   `extract_details.py` also accepts `--only 430,V02` to redo specific events and `--delay SECONDS` to stay under free-tier rate limits.

4. Review the result and commit `data/processed/`:

   ```bash
   uv run python scripts/validate_data.py     # lists missing PDFs, rubrics, competencies and other gaps
   ```

For a new season, delete the old `data/processed/text/` and `data/processed/details/` files first, or run each script with `--force`. Otherwise old output is kept.

## Deploy to Streamlit Community Cloud

1. Push the repo to GitHub. Do not commit `.env`, `.streamlit/secrets.toml` or `data/pdfs/`.
2. At <https://share.streamlit.io>, choose **Create app** and select the repo and branch.
3. Set the main file to `app.py`.
4. Under **Advanced settings**, pick Python 3.13. The version cannot be changed after deploying.
5. Under **Advanced settings → Secrets**, add:

   ```toml
   GEMINI_API_KEY = "your-key"
   # REPORT_EMAIL = "you@example.com"
   ```

6. Deploy. Dependencies are installed from `pyproject.toml` and `uv.lock`, so no `requirements.txt` is needed.

Use **Manage app → Logs** to debug. Gemini failures appear as `Gemini API error: code=...` (404 = model name, 400/403 = key, 429 = rate limit). Pushing to the branch redeploys automatically.

Public-app limits (see `bpa_app/config.py`): 30 AI calls per session per hour, 5 evaluations per session per hour, and 900 AI calls per day across all users.

## Change the Gemini models

Two tiers are used: **fast** for search, Q&A and quizzes, and **smart** for detail extraction and submission evaluation. Defaults are set in `bpa_app/config.py`:

| Tier | Default |
| --- | --- |
| Fast (`LLM_MODEL_FAST`) | `gemini-3.5-flash-lite` |
| Smart (`LLM_MODEL_SMART`) | `gemini-3.8-flash` |

To change them without editing code, set the variables in `.env` locally or in the Streamlit Cloud Secrets:

```toml
LLM_MODEL_FAST = "gemini-3.5-flash-lite"
LLM_MODEL_SMART = "gemini-3.8-flash"
```

To change the defaults for everyone, edit `_MODEL_DEFAULTS` in `bpa_app/config.py`. Current model IDs and availability are at <https://ai.google.dev/gemini-api/docs/models>. Older 2.5 models return a 404 for new API keys. After changing models, run `scripts/smoke_gemini.py`.
