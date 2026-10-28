"""All LLM calls go through here; the provider is chosen by config.LLM_PROVIDER."""

import logging
import random
import re
import time
from collections.abc import Callable, Iterable, Iterator
from functools import cache
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from bpa_app import config
from bpa_app.data import load_event_text, select_rubric
from bpa_app.models import (
    DIVISIONS,
    EVENT_TYPES,
    FORMATS,
    PARTICIPATION,
    QUIZ_CHOICES,
    CriterionScore,
    Evaluation,
    Event,
    Quiz,
    QuizQuestion,
    RubricItem,
    SearchFilters,
    SearchHit,
    SearchResult,
)
from bpa_app.prompts import DIFFICULTIES, evaluate_prompt, nl_search_prompt, quiz_prompt

MAX_ATTEMPTS = 3
MAX_SEARCH_RESULTS = 12
MIN_PREFIX_MATCH = 20
_RETRY_STATUSES = {429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """A failure whose message is safe to show to users."""


class _Transient(Exception):
    """A retryable failure (rate limit, server error, network)."""


def supports_pdf() -> bool:
    """Only Gemini accepts raw PDFs; Cortex needs extracted text."""
    return config.LLM_PROVIDER == config.PROVIDER_GEMINI


def _retry[T](call: Callable[[], T]) -> T:
    for attempt in range(MAX_ATTEMPTS):
        try:
            return call()
        except _Transient as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise LLMError(
                    "The AI service is busy right now. Please try again in a minute."
                ) from exc
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


# --- Cortex (private network) -------------------------------------------------


@cache
def _cortex_client() -> httpx.Client:
    if config.CORTEX_CA_BUNDLE:
        return httpx.Client(verify=config.CORTEX_CA_BUNDLE, timeout=120.0)
    # The corporate proxy's root CA lives in the OS trust store, not in certifi.
    import ssl

    import truststore

    return httpx.Client(
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=120.0
    )


def _cortex_chat(
    prompt: str,
    system: str | None,
    model: str,
    temperature: float,
    json_mode: bool,
) -> str:
    messages = [{"role": "user", "content": prompt}]
    if not config.CORTEX_BASE_URL:
        raise LLMError("CORTEX_API_BASE_URL is not set. Add it to .env.")
    if system:
        messages.insert(0, {"role": "system", "content": system})
    body: dict[str, Any] = {"messages": messages, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    url = f"{config.CORTEX_BASE_URL.rstrip('/')}/openai/deployments/{model}/chat/completions"
    headers = {"api-key": config.get_api_key(), "use-case": config.CORTEX_USE_CASE}
    params = {"api-version": config.CORTEX_API_VERSION}

    def call() -> str:
        try:
            resp = _cortex_client().post(url, headers=headers, params=params, json=body)
        except httpx.ConnectError as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                raise LLMError(
                    "TLS certificate check failed. Set CORTEX_CA_BUNDLE to the "
                    "corporate CA bundle (.pem) in .env."
                ) from exc
            raise _Transient from exc
        except httpx.TransportError as exc:
            raise _Transient from exc
        if resp.status_code in _RETRY_STATUSES:
            raise _Transient
        if resp.status_code in (401, 403):
            raise LLMError("Cortex rejected the token. Refresh CORTEX_TOKEN and retry.")
        if resp.status_code != 200:
            raise LLMError(f"Cortex request failed (HTTP {resp.status_code}).")
        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("The AI service sent an unexpected response.") from exc

    return _retry(call)


# --- Gemini (public deployment) -----------------------------------------------


@cache
def _gemini_client() -> Any:
    from google import genai

    return genai.Client(api_key=config.get_api_key())


def _gemini_config[M: BaseModel](
    system: str | None, temperature: float, schema: type[M] | None
) -> Any:
    from google.genai import types

    extra: dict[str, Any] = {}
    if schema is not None:
        extra = {"response_mime_type": "application/json", "response_schema": schema}
    return types.GenerateContentConfig(
        system_instruction=system, temperature=temperature, **extra
    )


def _gemini_contents(prompt: str, pdf: bytes | None) -> Any:
    if pdf is None:
        return prompt
    from google.genai import types

    return [types.Part.from_bytes(data=pdf, mime_type="application/pdf"), prompt]


def _gemini_error(exc: Any) -> LLMError:
    """Log the API's reason (for the host's logs) and return a user-safe error."""
    logger.error(
        "Gemini API error: code=%s status=%s message=%.300s",
        getattr(exc, "code", None),
        getattr(exc, "status", None),
        getattr(exc, "message", ""),
    )
    code = getattr(exc, "code", None)
    reason = str(getattr(exc, "message", "")).lower()
    if code in (401, 403) or (code == 400 and "api key" in reason):
        return LLMError(
            "The AI service rejected the API key or access. Tell the site owner."
        )
    if code == 404:
        return LLMError("The configured AI model was not found. Tell the site owner.")
    return LLMError(f"Gemini request failed (HTTP {code}).")


def _gemini_generate[M: BaseModel](
    prompt: str,
    system: str | None,
    model: str,
    temperature: float,
    schema: type[M] | None = None,
    pdf: bytes | None = None,
) -> str:
    from google.genai import errors

    cfg = _gemini_config(system, temperature, schema)

    def call() -> str:
        try:
            resp = _gemini_client().models.generate_content(
                model=model, contents=_gemini_contents(prompt, pdf), config=cfg
            )
        except errors.APIError as exc:
            if exc.code in _RETRY_STATUSES:
                logger.warning("Gemini transient error: code=%s", exc.code)
                raise _Transient from exc
            raise _gemini_error(exc) from exc
        except httpx.TransportError as exc:
            raise _Transient from exc
        return resp.text or ""

    return _retry(call)


# --- Public API ---------------------------------------------------------------


def generate_text(
    prompt: str,
    *,
    system: str | None = None,
    model: str = config.MODEL_FAST,
    temperature: float = 0.2,
) -> str:
    if config.LLM_PROVIDER == config.PROVIDER_CORTEX:
        return _cortex_chat(prompt, system, model, temperature, json_mode=False)
    return _gemini_generate(prompt, system, model, temperature)


def stream_text(
    prompt: str,
    *,
    system: str | None = None,
    model: str = config.MODEL_FAST,
    temperature: float = 0.2,
) -> Iterator[str]:
    """Yield answer chunks; Cortex does not stream, so it yields one chunk."""
    if config.LLM_PROVIDER == config.PROVIDER_CORTEX:
        yield generate_text(prompt, system=system, model=model, temperature=temperature)
        return

    from google.genai import errors

    cfg = _gemini_config(system, temperature, None)
    got_text = False
    try:
        for chunk in _gemini_client().models.generate_content_stream(
            model=model, contents=prompt, config=cfg
        ):
            if chunk.text:
                got_text = True
                yield chunk.text
    except errors.APIError as exc:
        raise _gemini_error(exc) from exc
    except httpx.TransportError as exc:
        raise LLMError("Could not reach the AI service. Please try again.") from exc
    if not got_text:
        logger.warning("Gemini returned an empty stream (possibly safety-blocked)")
        raise LLMError("The AI didn't return an answer. Try rephrasing the question.")


def generate_structured[M: BaseModel](
    prompt: str,
    schema: type[M],
    *,
    system: str | None = None,
    model: str = config.MODEL_SMART,
    temperature: float = 0.1,
    pdf: bytes | None = None,
) -> M:
    """Return a validated `schema` instance; `pdf` is Gemini-only (see supports_pdf)."""
    if config.LLM_PROVIDER == config.PROVIDER_CORTEX:
        if pdf is not None:
            raise LLMError("PDF input is not supported by Cortex; send extracted text.")
        # json_object mode has no schema parameter, so the schema goes in the prompt.
        schema_prompt = (
            f"{prompt}\n\nRespond with a single JSON object matching this JSON Schema:\n"
            f"{schema.model_json_schema()}"
        )
        raw = _cortex_chat(schema_prompt, system, model, temperature, json_mode=True)
    else:
        raw = _gemini_generate(prompt, system, model, temperature, schema, pdf)

    try:
        return schema.model_validate_json(raw)
    except ValidationError as exc:
        raise LLMError(
            "The AI returned an unexpected format. Please try again."
        ) from exc


def _canonical(values: list[str] | None, allowed: Iterable[str]) -> list[str] | None:
    """Map model-supplied filter values onto allowed spellings; drop unknown ones."""
    lookup = {a.casefold(): a for a in allowed}
    found = [
        lookup[v.strip().casefold()]
        for v in values or []
        if v.strip().casefold() in lookup
    ]
    return list(dict.fromkeys(found)) or None


def clean_search_result(result: SearchResult, events: list[Event]) -> SearchResult:
    """Drop unknown/duplicate ids, cap the list, and keep only valid filter values."""
    known = {e.id for e in events}
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for hit in result.results:
        event_id = hit.id.strip()
        if event_id in known and event_id not in seen:
            seen.add(event_id)
            hits.append(SearchHit(id=event_id, reason=hit.reason.strip()))
        if len(hits) == MAX_SEARCH_RESULTS:
            break

    raw = result.filters
    filters = SearchFilters(
        formats=_canonical(raw.formats, FORMATS),
        participation=_canonical(raw.participation, PARTICIPATION),
        event_types=_canonical(raw.event_types, EVENT_TYPES),
        divisions=_canonical(raw.divisions, DIVISIONS),
        subjects=_canonical(raw.subjects, {e.subject for e in events}),
        certification_only=True if raw.certification_only else None,
        presubmit_only=True if raw.presubmit_only else None,
    )
    return SearchResult(
        filters=filters, results=hits, interpretation=result.interpretation.strip()
    )


def nl_search(query: str, events: list[Event]) -> SearchResult:
    """Interpret a natural-language query against the catalog (uses MODEL_FAST)."""
    result = generate_structured(
        nl_search_prompt(query, events),
        SearchResult,
        model=config.MODEL_FAST,
        temperature=0.1,
    )
    return clean_search_result(result, events)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _take_matching(name: str, remaining: list[RubricItem]) -> RubricItem | None:
    """Find the rubric item the model meant, tolerating small wording changes."""
    key = _norm(name)
    for item in remaining:
        if _norm(item.criterion) == key:
            return item
    if len(key) >= MIN_PREFIX_MATCH:
        for item in remaining:
            other = _norm(item.criterion)
            if other.startswith(key) or key.startswith(other):
                return item
    return None


def _strip_all(values: list[str]) -> list[str]:
    return [v.strip() for v in values if v.strip()]


def clean_evaluation(result: Evaluation, rubric: list[RubricItem]) -> Evaluation:
    """Keep only real rubric criteria, with rubric max points and recomputed totals."""
    remaining = list(rubric)
    criteria: list[CriterionScore] = []
    for scored in result.criteria:
        item = _take_matching(scored.criterion, remaining)
        if item is None:
            continue
        remaining.remove(item)
        points = scored.estimated_points
        if item.max_points is None or points is None:
            points = None
        else:
            points = round(min(max(points, 0.0), item.max_points), 2)
        criteria.append(
            CriterionScore(
                criterion=" ".join(item.criterion.split()),
                max_points=item.max_points,
                estimated_points=points,
                evidence=scored.evidence.strip(),
                suggestions=scored.suggestions.strip(),
            )
        )

    counted = [
        c
        for c in criteria
        if c.max_points is not None and c.estimated_points is not None
    ]
    return Evaluation(
        criteria=criteria,
        missing_requirements=_strip_all(result.missing_requirements),
        strengths=_strip_all(result.strengths),
        top_3_improvements=_strip_all(result.top_3_improvements)[:3],
        estimated_total=round(sum(c.estimated_points or 0 for c in counted), 2),
        max_total=sum(c.max_points or 0 for c in counted),
        cannot_assess=_strip_all(result.cannot_assess),
    )


def evaluate_submission(
    event: Event,
    text: str,
    pdf_bytes: bytes | None,
    notes: str = "",
    sections: list[str] | None = None,
) -> Evaluation:
    """Score a draft against the event rubric (uses MODEL_SMART).

    A PDF is sent as bytes when the provider accepts it (so visual design counts);
    otherwise the extracted text is sent. `sections` limits which rubrics are used.
    """
    rubric = select_rubric(event.details, sections) if event.details else []
    if not rubric:
        raise LLMError("This event has no scoring rubric to evaluate against.")
    use_pdf = pdf_bytes is not None and supports_pdf()
    if not use_pdf and not text.strip():
        raise LLMError(
            "No readable text was found, and this AI service can't read PDFs "
            "directly. Please paste your text instead."
        )
    prompt = evaluate_prompt(
        event, rubric, load_event_text(event.id), None if use_pdf else text, notes
    )
    result = generate_structured(
        prompt,
        Evaluation,
        model=config.MODEL_SMART,
        temperature=0.0,
        pdf=pdf_bytes if use_pdf else None,
    )
    return clean_evaluation(result, rubric)


# Options like these only make sense in their original order, so never shuffle them.
_ORDER_DEPENDENT = ("of the above", "both a and", "a and b", "neither")


def _match_competency(name: str, competencies: list[str]) -> str:
    key = _norm(name)
    for competency in competencies:
        if _norm(competency) == key:
            return competency
    if len(key) >= MIN_PREFIX_MATCH:
        for competency in competencies:
            other = _norm(competency)
            if other.startswith(key) or key.startswith(other):
                return competency
    return name.strip()


def clean_quiz(
    quiz: Quiz,
    competencies: list[str],
    n: int,
    rng: random.Random | None = None,
) -> Quiz:
    """Keep well-formed, distinct questions and shuffle answers to avoid position bias."""
    rng = rng or random.Random()
    seen: set[str] = set()
    questions: list[QuizQuestion] = []
    for raw in quiz.questions:
        text = raw.question.strip()
        choices = [c.strip() for c in raw.choices]
        key = _norm(text)
        if (
            not text
            or key in seen
            or len(choices) != QUIZ_CHOICES
            or not all(choices)
            or len({c.casefold() for c in choices}) != QUIZ_CHOICES
            or not 0 <= raw.answer_index < QUIZ_CHOICES
        ):
            continue
        seen.add(key)
        answer = choices[raw.answer_index]
        if not any(p in " ".join(choices).casefold() for p in _ORDER_DEPENDENT):
            rng.shuffle(choices)
        questions.append(
            QuizQuestion(
                question=text,
                choices=choices,
                answer_index=choices.index(answer),
                explanation=raw.explanation.strip(),
                competency=_match_competency(raw.competency, competencies),
            )
        )
        if len(questions) == n:
            break
    if not questions:
        raise LLMError("The AI didn't return usable questions. Please try again.")
    return Quiz(questions=questions)


def generate_quiz(
    event: Event,
    competencies: list[str] | None = None,
    n: int = 10,
    difficulty: str = "medium",
    avoid: list[str] | None = None,
) -> Quiz:
    """Write practice questions from the event's competencies (uses MODEL_FAST).

    `competencies` limits the topics (default: all); `avoid` lists earlier questions
    that a new set should not repeat.
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}")
    available = event.details.competencies if event.details else []
    if not available:
        raise LLMError("This event has no competencies to build questions from.")
    chosen = [c for c in competencies or [] if c in available] or available
    prompt = quiz_prompt(event, chosen, n, difficulty, load_event_text(event.id), avoid)
    result = generate_structured(prompt, Quiz, model=config.MODEL_FAST, temperature=0.8)
    return clean_quiz(result, chosen, n)
