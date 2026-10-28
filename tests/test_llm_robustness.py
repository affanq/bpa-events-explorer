import httpx
import pytest

from bpa_app import config, llm
from bpa_app.models import SearchResult


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    monkeypatch.setenv("CORTEX_TOKEN", "test-token")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def _cortex(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_CORTEX)
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: response))
    monkeypatch.setattr(llm, "_cortex_client", lambda: client)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>Proxy login page</html>"),  # not JSON
        httpx.Response(200, json={"error": "no choices"}),  # missing key
        httpx.Response(200, json={"choices": []}),  # empty list
        httpx.Response(200, json={"choices": [{"message": None}]}),  # wrong type
        httpx.Response(200, json=["unexpected"]),  # wrong shape
    ],
    ids=["html", "no-choices-key", "empty-choices", "null-message", "list-body"],
)
def test_cortex_garbage_response_is_a_friendly_llm_error(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _cortex(monkeypatch, response)
    with pytest.raises(llm.LLMError, match="unexpected response"):
        llm.generate_text("hi")


def test_cortex_empty_content_is_returned_as_an_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cortex(
        monkeypatch,
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    )
    assert llm.generate_text("hi") == ""


def test_structured_call_on_a_garbage_body_is_still_an_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cortex(
        monkeypatch,
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
    )
    with pytest.raises(llm.LLMError, match="unexpected format"):
        llm.generate_structured("q", SearchResult)


class _BrokenGemini:
    """A Gemini client whose network calls fail the way a dropped connection does."""

    def __init__(self) -> None:
        self.calls = 0
        outer = self

        class Models:
            def generate_content(self, **_kwargs):
                outer.calls += 1
                raise httpx.ConnectError("connection dropped")

            def generate_content_stream(self, **_kwargs):
                outer.calls += 1
                raise httpx.ReadTimeout("timed out")

        self.models = Models()


def test_gemini_network_failure_is_retried_then_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_GEMINI)
    broken = _BrokenGemini()
    monkeypatch.setattr(llm, "_gemini_client", lambda: broken)
    with pytest.raises(llm.LLMError, match="busy"):
        llm.generate_text("hi")
    assert broken.calls == llm.MAX_ATTEMPTS


def test_gemini_stream_network_failure_is_an_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_GEMINI)
    monkeypatch.setattr(llm, "_gemini_client", lambda: _BrokenGemini())
    with pytest.raises(llm.LLMError, match="Could not reach"):
        list(llm.stream_text("hi"))


class _ApiErrorGemini:
    """A Gemini client that answers with an HTTP error or an empty stream."""

    def __init__(
        self, code: int | None = None, chunks: list[str] | None = None
    ) -> None:
        self.calls = 0
        outer = self

        class Chunk:
            def __init__(self, text: str) -> None:
                self.text = text

        class Models:
            def generate_content(self, **_kwargs):
                outer.calls += 1
                from google.genai import errors

                raise errors.APIError(
                    code, {"error": {"message": "reason", "status": "X"}}
                )

            def generate_content_stream(self, **_kwargs):
                if code is not None:
                    return self.generate_content()
                return iter([Chunk(t) for t in chunks or []])

        self.models = Models()


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (403, "API key"),
        (401, "API key"),
        (404, "model was not found"),
        (400, "HTTP 400"),
    ],
)
def test_gemini_api_errors_get_actionable_messages(
    monkeypatch: pytest.MonkeyPatch, code: int, message: str
) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_GEMINI)
    monkeypatch.setattr(llm, "_gemini_client", lambda: _ApiErrorGemini(code))
    with pytest.raises(llm.LLMError, match=message):
        llm.generate_text("hi")
    with pytest.raises(llm.LLMError, match=message):
        list(llm.stream_text("hi"))


def test_gemini_429_is_retried_then_reported_as_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_GEMINI)
    fake = _ApiErrorGemini(429)
    monkeypatch.setattr(llm, "_gemini_client", lambda: fake)
    with pytest.raises(llm.LLMError, match="busy"):
        llm.generate_text("hi")
    assert fake.calls == llm.MAX_ATTEMPTS


def test_gemini_empty_stream_is_an_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_GEMINI)
    monkeypatch.setattr(llm, "_gemini_client", lambda: _ApiErrorGemini(chunks=[]))
    with pytest.raises(llm.LLMError, match="didn't return an answer"):
        list(llm.stream_text("hi"))


def test_gemini_stream_with_text_yields_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_GEMINI)
    monkeypatch.setattr(
        llm, "_gemini_client", lambda: _ApiErrorGemini(chunks=["a", "", "b"])
    )
    assert list(llm.stream_text("hi")) == ["a", "b"]
