"""Small presentation helpers shared by pages (pure functions, easy to test)."""

import re
from collections.abc import Callable
from urllib.parse import quote

import pandas as pd

from bpa_app import config
from bpa_app.models import CriterionScore, Evaluation, Event, RubricItem

AI_DISCLAIMER = (
    "AI-generated – may contain errors. Always check the official guidelines."
)
PRACTICE_DISCLAIMER = "Practice estimate only – actual judges' scores will differ."
QUIZ_DISCLAIMER = (
    "Practice questions are AI-generated and are not actual BPA test questions."
)
GUIDELINES_RELEASE = "Release v1.0, September 1, 2026"
BPA_WEBSITE = "https://bpa.org"
REPORT_SUBJECT = "BPA Event Explorer: data error"
_CODE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)
_PROVIDER_NAMES = {
    config.PROVIDER_GEMINI: "Google Gemini",
    config.PROVIDER_CORTEX: "the Cortex AI service",
}


def provider_name() -> str:
    return _PROVIDER_NAMES.get(config.LLM_PROVIDER, "the AI provider")


def report_error_link(email: str | None = None) -> str:
    return f"mailto:{email or config.REPORT_EMAIL}?subject={quote(REPORT_SUBJECT)}"


def guideline_links_dataframe(events: list[Event]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Event": e.id,
                "Title": e.title,
                "Divisions": "/".join(e.divisions),
                "Official PDF": e.view_url,
            }
            for e in events
        ]
    )


def rubric_dataframe(items: list[RubricItem]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Section": item.section or "",
                "Criterion": item.criterion,
                "Max points": item.max_points,
                "What earns high marks": item.description or "",
            }
            for item in items
        ]
    )


def badges(event: Event) -> str:
    parts = [f":blue-badge[{event.format}]", f":green-badge[{event.participation}]"]
    parts += [f":orange-badge[{t}]" for t in event.event_type]
    parts += [f":gray-badge[{d}]" for d in event.divisions]
    if event.certification:
        parts.append(":violet-badge[🏅 Certification]")
    if event.presubmit:
        parts.append(":red-badge[📤 Presubmit]")
    return " ".join(parts)


def escape_md(text: str) -> str:
    """Stop `$` in guideline text (e.g. fees) from being rendered as math."""
    return text.replace("$", "\\$")


def escape_md_keep_code(text: str) -> str:
    """Like escape_md, but leave `$` inside code spans and fenced blocks untouched."""
    parts = _CODE.split(text)  # odd items are the code pieces
    return "".join(p if i % 2 else escape_md(p) for i, p in enumerate(parts))


def team_size_text(event: Event) -> str:
    if event.participation == "Individual":
        return "Individual event"
    low = event.details.team_size_min if event.details else None
    high = event.details.team_size_max if event.details else None
    if low and high:
        return f"{low} members" if low == high else f"{low}–{high} members"
    if high:
        return f"Up to {high} members"
    if low:
        return f"At least {low} members"
    return "Team size not stated"


NOT_AVAILABLE = "Not available yet"  # details haven't been extracted for the event
NOT_STATED = "Not stated"
DIVISION_LABELS = {
    "MS": "Middle School (MS)",
    "HS": "High School (HS)",
    "College": "College",
}


def yes_no(value: bool | None) -> str:
    return NOT_STATED if value is None else "Yes" if value else "No"


def rubric_total_lines(event: Event) -> list[str]:
    details = event.details
    if details is None:
        return [NOT_AVAILABLE]
    lines = []
    if details.rubric_total_points is not None:
        lines.append(f"{details.rubric_total_points:g} points in total")
    lines += [f"{s.section}: {s.total_points:g}" for s in details.rubric_section_totals]
    if lines:
        return lines
    if details.rubric:
        listed = sum(i.max_points for i in details.rubric if i.max_points is not None)
        return [f"{listed:g} (sum of listed items)"]
    if event.event_type == ["Testing"]:
        return ["No rubric (testing event)"]
    return [NOT_STATED]


def _detail_list(event: Event, attribute: str) -> list[str]:
    if event.details is None:
        return [NOT_AVAILABLE]
    return list(getattr(event.details, attribute)) or [NOT_STATED]


# Each field returns lines to show for one event, in comparison order.
COMPARE_FIELDS: dict[str, Callable[[Event], list[str]]] = {
    "Format": lambda e: [e.format],
    "Participation": lambda e: [e.participation],
    "Team size": lambda e: [team_size_text(e)],
    "Type": lambda e: [" / ".join(e.event_type)],
    "Divisions": lambda e: [", ".join(DIVISION_LABELS[d] for d in e.divisions)],
    "Time limits": lambda e: _detail_list(e, "time_limits"),
    "Submission requirements": lambda e: _detail_list(e, "submission_requirements"),
    "Presubmit": lambda e: [yes_no(e.presubmit)],
    "Pre-submit items": lambda e: _detail_list(e, "presubmit_items"),
    "Certification": lambda e: [yes_no(e.certification)],
    "Rubric total": rubric_total_lines,
}


def checklist_markdown(
    event: Event, sections: dict[str, list[str]], done: dict[str, bool]
) -> str:
    """Markdown checklist; `done` maps "{section}-{index}" to checked state."""
    lines = [f"# Checklist: {event.id} {event.title}", ""]
    for name, items in sections.items():
        if not items:
            continue
        lines += [f"## {name}", ""]
        for index, item in enumerate(items):
            mark = "x" if done.get(f"{name}-{index}") else " "
            lines.append(f"- [{mark}] {item}")
        lines.append("")
    if source := event.view_url:
        lines.append(f"Official guideline: {source}")
    return "\n".join(lines).rstrip() + "\n"


def score_percent(evaluation: Evaluation) -> float:
    if evaluation.max_total <= 0:
        return 0.0
    return evaluation.estimated_total / evaluation.max_total * 100


def _points(value: float | None) -> str:
    return "–" if value is None else f"{value:g}"


def score_label(criterion: CriterionScore) -> str:
    """Like "14 / 25", or "required element" for pass/fail rows without points."""
    if criterion.max_points is None:
        return "required element"
    return f"{_points(criterion.estimated_points)} / {_points(criterion.max_points)}"


def feedback_markdown(event: Event, evaluation: Evaluation) -> str:
    lines = [
        f"# Practice feedback: {event.id} {event.title}",
        "",
        f"> {PRACTICE_DISCLAIMER}",
        "",
        (
            f"**Estimated score: {evaluation.estimated_total:g} / "
            f"{evaluation.max_total:g} ({score_percent(evaluation):.0f}%)**"
        ),
        "",
    ]
    if evaluation.criteria:
        lines += ["## Criteria", ""]
    for c in evaluation.criteria:
        lines += [
            f"### {c.criterion} ({score_label(c)})",
            "",
            f"**Evidence:** {c.evidence}",
            "",
            f"**How to improve:** {c.suggestions}",
            "",
        ]
    sections = [
        ("Missing requirements", evaluation.missing_requirements, "-"),
        ("Strengths", evaluation.strengths, "-"),
        ("Top 3 improvements", evaluation.top_3_improvements, "1."),
        ("Could not be assessed from a document", evaluation.cannot_assess, "-"),
    ]
    for title, items, bullet in sections:
        if items:
            lines += [f"## {title}", ""] + [f"{bullet} {item}" for item in items] + [""]
    return "\n".join(lines).rstrip() + "\n"
