import math
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import TypeAdapter

from bpa_app.config import CATALOG_JSON, EVENTS_JSON, TEXT_DIR
from bpa_app.models import Event, EventDetails, RubricItem


class NormalizationError(ValueError):
    """Raised when a source value cannot be mapped to a known code."""


_DIVISION_TOKENS = {
    "middle school": "MS",
    "ms": "MS",
    "high school": "HS",
    "highschool": "HS",
    "hs": "HS",
    "college": "College",
}
_DIVISION_ORDER = ("MS", "HS", "College")

_TYPE_TOKENS = {"testing": "Testing", "judged": "Judged"}
_TYPE_ORDER = ("Testing", "Judged")

# "individuai" is a typo (capital i) in the source workbook.
_PARTICIPATION = {
    "individual": "Individual",
    "individuai": "Individual",
    "team": "Team",
}


def load_catalog(path: Path = CATALOG_JSON) -> list[Event]:
    return TypeAdapter(list[Event]).validate_json(path.read_bytes())


@cache
def load_events(path: Path = EVENTS_JSON) -> list[Event]:
    """Read events.json once per process; callers must not mutate the result."""
    return TypeAdapter(list[Event]).validate_json(path.read_bytes())


def get_event(event_id: str) -> Event | None:
    return next((e for e in load_events() if e.id == event_id), None)


def load_event_text(event_id: str) -> str | None:
    """Full extracted guideline text for a catalog event, or None if not extracted."""
    path = TEXT_DIR / f"{event_id}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


UNNAMED_SECTION = "Rubric"


def rubric_sections(details: EventDetails) -> list[str]:
    """Distinct rubric names in document order (unnamed items share one name)."""
    return list(dict.fromkeys(i.section or UNNAMED_SECTION for i in details.rubric))


def select_rubric(
    details: EventDetails, sections: list[str] | None = None
) -> list[RubricItem]:
    """Rubric items from the given sections; None means every section."""
    if sections is None:
        return list(details.rubric)
    return [i for i in details.rubric if (i.section or UNNAMED_SECTION) in sections]


def filter_events(
    events: list[Event],
    formats: list[str] | None = None,
    participation: list[str] | None = None,
    event_types: list[str] | None = None,
    divisions: list[str] | None = None,
    subjects: list[str] | None = None,
    certification_only: bool = False,
    presubmit_only: bool = False,
) -> list[Event]:
    """AND across filters; an empty or None filter matches everything."""
    return [
        e
        for e in events
        if (not formats or e.format in formats)
        and (not participation or e.participation in participation)
        and (not event_types or set(e.event_type) & set(event_types))
        and (not divisions or set(e.divisions) & set(divisions))
        and (not subjects or e.subject in subjects)
        and (not certification_only or e.certification is True)
        and (not presubmit_only or e.presubmit is True)
    ]


_STOPWORDS = {"a", "an", "and", "the", "for", "of", "in", "on", "to", "with", "or"}

MAX_QUERY_CHARS = 300


def normalize_query(query: str) -> str:
    """Lowercase, collapse whitespace and drop trailing punctuation (cache key)."""
    text = " ".join(query.lower().split())[:MAX_QUERY_CHARS]
    return text.rstrip("?!. ")


def _word_start(token: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(token)}", text) is not None


def keyword_search(events: list[Event], query: str) -> list[Event]:
    """Rank events by query words: title x3, keywords x2, summary and competencies x1."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in _STOPWORDS]
    if not tokens:
        return []

    scored: list[tuple[int, Event]] = []
    for event in events:
        title = event.title.lower()
        details = event.details
        keywords = [k.lower() for k in details.keywords] if details else []
        summary = details.summary.lower() if details else ""
        competencies = [c.lower() for c in details.competencies] if details else []

        score = 0
        for token in tokens:
            score += 3 * _word_start(token, title)
            score += 2 * any(_word_start(token, k) for k in keywords)
            score += _word_start(token, summary)
            score += any(_word_start(token, c) for c in competencies)
        if score:
            scored.append((score, event))

    scored.sort(key=lambda pair: -pair[0])  # stable: ties keep catalog order
    return [event for _, event in scored]


_DIVISION_PHRASES = {
    "MS": "middle school students",
    "HS": "high school students",
    "College": "college students",
}
_PREFERENCE_PHRASES = {
    "test": "that are multiple-choice testing events",
    "project": "that are judged project events",
    "presentation": "that involve giving a presentation",
    "speech": "that involve public speaking",
}
_PREFERENCE_TYPES = {
    "test": ["Testing"],
    "project": ["Judged"],
    "presentation": ["Judged"],
    "speech": ["Judged"],
}


def _join_words(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return f"{', '.join(words[:-1])} and {words[-1]}"


@dataclass(frozen=True)
class HelpAnswers:
    """Answers to the "Help me choose" questions; None means no preference."""

    division: str | None = None  # MS, HS or College
    participation: str | None = None  # Individual or Team
    preference: str | None = None  # test, project, presentation or speech
    interests: tuple[str, ...] = ()
    format: str | None = None  # In-Person or Virtual

    def is_empty(self) -> bool:
        return not (
            self.division
            or self.participation
            or self.preference
            or self.interests
            or self.format
        )

    def to_query(self) -> str:
        """The answers as a natural-language search query."""
        kind = "individual" if self.participation == "Individual" else "team"
        subject = f"{kind} events" if self.participation else "events"
        parts = [
            f"{subject} for {_DIVISION_PHRASES[self.division]}"
            if self.division
            else subject
        ]
        if self.preference:
            parts.append(_PREFERENCE_PHRASES[self.preference])
        if self.interests:
            parts.append(f"about {_join_words(list(self.interests))}")
        if self.format:
            parts.append(f"{self.format.lower()} only")
        return ", ".join(parts)

    def filter_kwargs(self) -> dict[str, list[str] | None]:
        """Hard filters implied by the answers, for filter_events."""
        formats = None
        if self.format == "In-Person":
            formats = ["In-Person", "Open"]  # Open events don't say; keep them
        elif self.format:
            formats = [self.format]
        return {
            "formats": formats,
            "participation": [self.participation] if self.participation else None,
            "event_types": _PREFERENCE_TYPES.get(self.preference or ""),
            "divisions": [self.division] if self.division else None,
        }


def match_answers(events: list[Event], answers: HelpAnswers) -> list[Event]:
    """Non-AI matches: filter by the answers, then rank by the interests."""
    filtered = filter_events(events, **answers.filter_kwargs())
    if not answers.interests:
        return filtered
    ranked = keyword_search(filtered, " ".join(answers.interests))
    ranked_ids = {e.id for e in ranked}
    return ranked + [e for e in filtered if e.id not in ranked_ids]


def clean_str(value: Any) -> str | None:
    """Strip whitespace; blank and missing values become None."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_tokens(
    raw: Any,
    event_id: str,
    field: str,
    tokens: dict[str, str],
    order: tuple[str, ...],
) -> list[str]:
    text = clean_str(raw)
    if text is None:
        raise NormalizationError(f"Event {event_id}: missing {field}")
    codes: set[str] = set()
    for part in text.split("/"):
        code = tokens.get(part.strip().casefold())
        if code is None:
            raise NormalizationError(f"Event {event_id}: unrecognized {field} {raw!r}")
        codes.add(code)
    return [code for code in order if code in codes]


def normalize_division(raw: Any, event_id: str = "?") -> list[str]:
    return _normalize_tokens(
        raw, event_id, "division", _DIVISION_TOKENS, _DIVISION_ORDER
    )


def normalize_type(raw: Any, event_id: str = "?") -> list[str]:
    return _normalize_tokens(raw, event_id, "type", _TYPE_TOKENS, _TYPE_ORDER)


def normalize_participation(raw: Any, event_id: str = "?") -> str:
    text = clean_str(raw)
    if text is None:
        raise NormalizationError(f"Event {event_id}: missing participation")
    value = _PARTICIPATION.get(text.casefold())
    if value is None:
        raise NormalizationError(
            f"Event {event_id}: unrecognized participation {raw!r}"
        )
    return value


def parse_bool(raw: Any, event_id: str = "?") -> bool | None:
    """Parse real booleans or TRUE/FALSE strings; blank means unknown (None)."""
    if isinstance(raw, bool):
        return raw
    text = clean_str(raw)
    if text is None:
        return None
    if text.casefold() == "true":
        return True
    if text.casefold() == "false":
        return False
    raise NormalizationError(f"Event {event_id}: unrecognized boolean {raw!r}")


_TESTING_PATTERN = re.compile(
    r"\b(?:objective|written|online|multiple[- ]choice)\s+(?:test|exam)\b"
    r"|\bmultiple[- ]choice\b"
    r"|\b(?:test|exam)\s+(?:questions|time)\b"
    r"|\btest:",
    re.IGNORECASE,
)


def mentions_testing(details: EventDetails) -> str | None:
    """Return the matched phrase if the details clearly describe a test component."""
    parts = [
        details.summary,
        *details.time_limits,
        *details.submission_requirements,
        *details.competencies,
        *details.judging_notes,
        *details.what_to_bring,
    ]
    match = _TESTING_PATTERN.search("\n".join(parts))
    return match.group(0) if match else None


MISSING_TEXT = "missing text"
MISSING_DETAILS = "missing details"
EMPTY_RUBRIC = "judged, empty rubric"
TOTAL_MISMATCH = "rubric total mismatch"
NO_TEAM_SIZE = "team size missing"
PROBLEM_ORDER = (
    MISSING_TEXT,
    MISSING_DETAILS,
    EMPTY_RUBRIC,
    TOTAL_MISMATCH,
    NO_TEAM_SIZE,
)


@dataclass(frozen=True)
class Problem:
    event_id: str
    title: str
    kind: str
    detail: str


def _fmt(number: float) -> str:
    return f"{number:g}"


def _points(items: list[RubricItem]) -> float:
    return sum(i.max_points for i in items if i.max_points is not None)


def _total_mismatches(details: EventDetails) -> list[str]:
    mismatches: list[str] = []
    if details.rubric_total_points is not None and details.rubric:
        total = _points(details.rubric)
        if not math.isclose(total, details.rubric_total_points, abs_tol=0.01):
            mismatches.append(
                f"overall: stated {_fmt(details.rubric_total_points)}, items sum to {_fmt(total)}"
            )
    for section in details.rubric_section_totals:
        key = section.section.strip().casefold()
        items = [
            i for i in details.rubric if (i.section or "").strip().casefold() == key
        ]
        total = _points(items)
        if not math.isclose(total, section.total_points, abs_tol=0.01):
            mismatches.append(
                f"{section.section}: stated {_fmt(section.total_points)}, items sum to {_fmt(total)}"
            )
    return mismatches


def find_problems(events: list[Event]) -> list[Problem]:
    problems: list[Problem] = []
    for event in events:

        def add(kind: str, detail: str = "", event: Event = event) -> None:
            problems.append(Problem(event.id, event.title, kind, detail))

        if not event.has_text:
            add(
                MISSING_TEXT,
                "no local PDF" if event.pdf_file is None else "not extracted",
            )
        details = event.details
        if details is None:
            add(MISSING_DETAILS)
            continue

        if "Judged" in event.event_type and not details.rubric:
            add(EMPTY_RUBRIC)
        for mismatch in _total_mismatches(details):
            add(TOTAL_MISMATCH, mismatch)
        if event.participation == "Team" and (
            details.team_size_min is None or details.team_size_max is None
        ):
            add(NO_TEAM_SIZE)

    order = {kind: i for i, kind in enumerate(PROBLEM_ORDER)}
    return sorted(problems, key=lambda p: (order[p.kind], p.event_id.zfill(5)))
