"""Per-session hourly and global daily limits on AI calls (in memory, no storage)."""

import threading
import time
from datetime import date

import streamlit as st

from bpa_app import config

SESSION_WINDOW_SECONDS = 3600


class RateLimitError(Exception):
    """The caller exceeded a limit; the message is safe to show to users."""


class DailyCounter:
    def __init__(self) -> None:
        self._day: date | None = None
        self._count = 0
        self._lock = threading.Lock()

    def increment(self, today: date, limit: int) -> bool:
        with self._lock:
            if today != self._day:
                self._day, self._count = today, 0
            if self._count >= limit:
                return False
            self._count += 1
            return True


def check_limits(
    session_calls: list[float],
    counter: DailyCounter,
    now: float,
    *,
    per_session_per_hour: int,
    global_daily: int,
    kind: str = "search",
) -> None:
    """Record one AI call or raise RateLimitError; `session_calls` is mutated."""
    session_calls[:] = [t for t in session_calls if now - t < SESSION_WINDOW_SECONDS]
    if len(session_calls) >= per_session_per_hour:
        raise RateLimitError(
            f"You've reached the hourly limit for AI {kind}. Please try again later."
        )
    if not counter.increment(date.fromtimestamp(now), global_daily):
        raise RateLimitError(
            f"AI {kind} has reached its daily limit. Please try again tomorrow."
        )
    session_calls.append(now)


@st.cache_resource
def _daily_counter() -> DailyCounter:
    return DailyCounter()


def check_and_count(kind: str) -> tuple[bool, str]:
    """Charge one AI call to this session and the daily budget.

    Call right before every real LLM request in the app (not for cache hits).
    `kind` names the feature for the message, e.g. "search", "chat", "evaluation".
    Evaluations are counted in their own per-session bucket, so they neither use up
    nor are blocked by the general limit; every kind shares the global daily budget.
    Returns (True, "") when allowed, else (False, friendly message).
    """
    if kind == "evaluation":
        bucket, per_session = (
            "ai_call_times_evaluation",
            config.EVALUATIONS_PER_SESSION_PER_HOUR,
        )
    else:
        bucket, per_session = "ai_call_times", config.AI_CALLS_PER_SESSION_PER_HOUR
    try:
        check_limits(
            st.session_state.setdefault(bucket, []),
            _daily_counter(),
            time.time(),
            per_session_per_hour=per_session,
            global_daily=config.GLOBAL_DAILY_AI_CALLS,
            kind=kind,
        )
    except RateLimitError as exc:
        return False, str(exc)
    return True, ""
