"""Check every AI feature against the real Gemini API.

Usage (needs GEMINI_API_KEY in the environment or .env):
    uv run python scripts/smoke_gemini.py [--skip-pdf]

Forces LLM_PROVIDER=gemini; prints PASS/FAIL per feature and never prints keys.
"""

import argparse
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

os.environ["LLM_PROVIDER"] = "gemini"  # must be set before bpa_app.config is imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bpa_app import config, llm
from bpa_app.data import load_event_text, load_events
from bpa_app.models import Event
from bpa_app.prompts import event_qa_system, event_qa_user_prompt

SAMPLE_SUBMISSION = (
    "Our team will create a three minute promotional video for a local food bank. "
    "It opens with a clear problem statement, shows volunteers at work, and ends "
    "with a call to action and contact details."
)


def _pick(events: list[Event]) -> tuple[Event, Event]:
    rubric_event = next(e for e in events if e.details and e.details.rubric)
    quiz_event = next(e for e in events if e.details and e.details.competencies)
    return rubric_event, quiz_event


def _steps(events: list[Event], skip_pdf: bool) -> list[tuple[str, Callable[[], str]]]:
    rubric_event, quiz_event = _pick(events)

    def plain() -> str:
        return llm.generate_text(
            "Reply with the single word: ok", model=config.MODEL_FAST
        )

    def stream() -> str:
        text = load_event_text(quiz_event.id)
        chunks = list(
            llm.stream_text(
                event_qa_user_prompt([], "What is this event about?"),
                system=event_qa_system(quiz_event, text),
                model=config.MODEL_FAST,
            )
        )
        return f"{len(chunks)} chunk(s), {sum(map(len, chunks))} chars"

    def search() -> str:
        result = llm.nl_search(
            "virtual team events for high school involving video", events
        )
        return f"{len(result.hits)} hit(s)"

    def quiz() -> str:
        return f"{len(llm.generate_quiz(quiz_event, n=3).questions)} question(s)"

    def evaluate_text() -> str:
        result = llm.evaluate_submission(rubric_event, SAMPLE_SUBMISSION, None)
        return f"{result.estimated_total}/{result.max_total} points"

    def evaluate_pdf() -> str:
        pdf = next(config.PDF_DIR.glob("*.pdf"), None)
        if pdf is None:
            raise llm.LLMError("no PDF in data/pdfs to send")
        result = llm.evaluate_submission(rubric_event, "", pdf.read_bytes())
        return f"{result.estimated_total}/{result.max_total} points (sent {pdf.name})"

    steps = [
        ("generate_text", plain),
        ("stream_text (event Q&A)", stream),
        ("structured: SearchResult", search),
        ("structured: Quiz", quiz),
        ("structured: Evaluation (text)", evaluate_text),
    ]
    if not skip_pdf:
        steps.append(("structured: Evaluation (PDF bytes)", evaluate_pdf))
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-pdf", action="store_true", help="skip the PDF-bytes test"
    )
    args = parser.parse_args()

    print(
        f"provider={config.LLM_PROVIDER} fast={config.MODEL_FAST} smart={config.MODEL_SMART}"
    )
    failures = 0
    for name, step in _steps(load_events(), args.skip_pdf):
        start = time.perf_counter()
        try:
            detail = step()
            status = "PASS"
        except Exception as exc:  # noqa: BLE001 - report every failure kind
            detail, status = f"{type(exc).__name__}: {exc}", "FAIL"
            failures += 1
        print(f"{status}  {name:36} {time.perf_counter() - start:5.1f}s  {detail}")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
