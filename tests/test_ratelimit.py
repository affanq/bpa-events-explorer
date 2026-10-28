import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from bpa_app import config


@pytest.fixture(autouse=True)
def fresh_counter() -> None:
    st.cache_resource.clear()


def _eval_script() -> None:
    import streamlit as st

    from bpa_app import ratelimit

    log = st.session_state.setdefault("log", [])
    log.append(
        (
            ratelimit.check_and_count("evaluation")[0],
            ratelimit.check_and_count("chat")[0],
        )
    )


def test_evaluations_have_their_own_hourly_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "EVALUATIONS_PER_SESSION_PER_HOUR", 2)
    monkeypatch.setattr(config, "AI_CALLS_PER_SESSION_PER_HOUR", 3)
    monkeypatch.setattr(config, "GLOBAL_DAILY_AI_CALLS", 100)
    at = AppTest.from_function(_eval_script, default_timeout=30).run()
    at.run()
    at.run()
    # Evaluations stop after 2 while chat keeps its own 3; neither uses the other's quota.
    assert at.session_state["log"] == [(True, True), (True, True), (False, True)]
    assert len(at.session_state["ai_call_times_evaluation"]) == 2
    assert len(at.session_state["ai_call_times"]) == 3


def test_evaluations_still_count_toward_the_global_daily_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GLOBAL_DAILY_AI_CALLS", 1)
    at = AppTest.from_function(_eval_script, default_timeout=30).run()
    # The evaluation used the only daily call, so even chat is refused afterwards.
    assert at.session_state["log"] == [(True, False)]


def _script() -> None:
    import streamlit as st

    from bpa_app import ratelimit

    st.session_state.setdefault("log", []).append(ratelimit.check_and_count("chat"))


def _session() -> AppTest:
    return AppTest.from_function(_script, default_timeout=30)


def test_session_hourly_limit_returns_friendly_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "AI_CALLS_PER_SESSION_PER_HOUR", 2)
    monkeypatch.setattr(config, "GLOBAL_DAILY_AI_CALLS", 100)
    at = _session().run()
    at.run()
    at.run()

    first, second, third = at.session_state["log"]
    assert first == (True, "") and second == (True, "")
    allowed, message = third
    assert allowed is False
    assert "hourly limit for AI chat" in message
    assert len(at.session_state["ai_call_times"]) == 2  # blocked call is not counted


def test_global_daily_limit_is_shared_across_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "AI_CALLS_PER_SESSION_PER_HOUR", 10)
    monkeypatch.setattr(config, "GLOBAL_DAILY_AI_CALLS", 1)

    assert _session().run().session_state["log"] == [(True, "")]
    allowed, message = _session().run().session_state["log"][0]
    assert allowed is False
    assert "daily limit" in message
