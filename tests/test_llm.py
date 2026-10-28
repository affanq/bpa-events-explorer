import httpx
import pytest
from pydantic import BaseModel

from bpa_app import config, llm


class Answer(BaseModel):
    text: str


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


@pytest.fixture(autouse=True)
def cortex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", config.PROVIDER_CORTEX)
    monkeypatch.setenv("CORTEX_TOKEN", "test-token")
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        llm, "_cortex_client", lambda: _client(httpx.MockTransport(wrapped))
    )
    return seen


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_generate_text_sends_cortex_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(monkeypatch, lambda _r: _ok("hello"))
    assert llm.generate_text("hi", system="be brief") == "hello"
    request = seen[0]
    assert "/openai/deployments/" in request.url.path
    assert request.headers["api-key"] == "test-token"
    assert request.headers["use-case"] == config.CORTEX_USE_CASE
    assert request.url.params["api-version"] == config.CORTEX_API_VERSION


def test_generate_structured_validates_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: _ok('{"text": "ok"}'))
    assert llm.generate_structured("q", Answer) == Answer(text="ok")


def test_generate_structured_bad_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: _ok("not json"))
    with pytest.raises(llm.LLMError, match="unexpected format"):
        llm.generate_structured("q", Answer)


def test_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([httpx.Response(429), _ok("done")])
    seen = _install(monkeypatch, lambda _r: next(responses))
    assert llm.generate_text("hi") == "done"
    assert len(seen) == 2


def test_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(monkeypatch, lambda _r: httpx.Response(503))
    with pytest.raises(llm.LLMError, match="busy"):
        llm.generate_text("hi")
    assert len(seen) == llm.MAX_ATTEMPTS


def test_bad_token_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(monkeypatch, lambda _r: httpx.Response(401))
    with pytest.raises(llm.LLMError, match="token"):
        llm.generate_text("hi")
    assert len(seen) == 1


def test_cortex_rejects_pdf_input() -> None:
    with pytest.raises(llm.LLMError, match="PDF"):
        llm.generate_structured("q", Answer, pdf=b"%PDF")
    assert not llm.supports_pdf()
