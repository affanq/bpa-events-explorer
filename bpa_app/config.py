import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
PDF_DIR = DATA_DIR / "pdfs"
SOURCE_DIR = DATA_DIR / "source"
PROCESSED_DIR = DATA_DIR / "processed"
TEXT_DIR = PROCESSED_DIR / "text"
DETAILS_DIR = PROCESSED_DIR / "details"
EVENTS_JSON = PROCESSED_DIR / "events.json"
CATALOG_JSON = PROCESSED_DIR / "catalog.json"

load_dotenv(REPO_ROOT / ".env")

PROVIDER_GEMINI = "gemini"
PROVIDER_CORTEX = "cortex"

# "cortex" for testing on a private network; "gemini" for the public deployment.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", PROVIDER_GEMINI).lower()

_MODEL_DEFAULTS = {
    PROVIDER_GEMINI: ("gemini-3.5-flash-lite", "gemini-3.8-flash"),
    PROVIDER_CORTEX: (
        "gpt-4.1-2025-04-14-us-data-zone",
        "gpt-4.1-2025-04-14-us-data-zone",
    ),
}
_FAST_DEFAULT, _SMART_DEFAULT = _MODEL_DEFAULTS.get(
    LLM_PROVIDER, _MODEL_DEFAULTS[PROVIDER_GEMINI]
)
MODEL_FAST = os.environ.get("LLM_MODEL_FAST", _FAST_DEFAULT)
MODEL_SMART = os.environ.get("LLM_MODEL_SMART", _SMART_DEFAULT)

CORTEX_BASE_URL = os.environ.get("CORTEX_API_BASE_URL", "")
CORTEX_API_VERSION = os.environ.get("CORTEX_API_VERSION", "2024-02-01")
# Cortex requires a registered use-case header; replace with your own approved value.
CORTEX_USE_CASE = os.environ.get("CORTEX_USE_CASE", "bpa-events")
_DEFAULT_CA_BUNDLE = REPO_ROOT / "certs" / "custom_ca_bundle.pem"
CORTEX_CA_BUNDLE = (
    os.environ.get("CORTEX_CA_BUNDLE")
    or os.environ.get("REQUESTS_CA_BUNDLE")
    or (str(_DEFAULT_CA_BUNDLE) if _DEFAULT_CA_BUNDLE.exists() else None)
)

MAX_UPLOAD_MB = 10
MAX_UPLOAD_TEXT_CHARS = 60_000
AI_CALLS_PER_SESSION_PER_HOUR = 30
EVALUATIONS_PER_SESSION_PER_HOUR = 5  # evaluations have their own, tighter bucket
GLOBAL_DAILY_AI_CALLS = 900

PLACEHOLDER_REPORT_EMAIL = "your-email@example.com"
REPORT_EMAIL = os.environ.get("REPORT_EMAIL", PLACEHOLDER_REPORT_EMAIL)


def _get_secret(name: str) -> str:
    """Read a secret from the environment (.env), then st.secrets; raise if missing."""
    key = os.environ.get(name)
    if key:
        return key

    try:
        import streamlit as st

        key = st.secrets.get(name)
    except (ImportError, FileNotFoundError):  # no secrets.toml present
        key = None
    if key:
        return str(key)

    raise RuntimeError(
        f"{name} not found. Set it in .env or the environment (scripts), "
        "or in .streamlit/secrets.toml (app)."
    )


def get_api_key() -> str:
    """Return the API key for the active provider (never logged)."""
    if LLM_PROVIDER == PROVIDER_CORTEX:
        return _get_secret("CORTEX_TOKEN")
    return _get_secret("GEMINI_API_KEY")
