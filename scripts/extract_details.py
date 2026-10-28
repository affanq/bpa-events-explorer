"""Extract structured EventDetails from each guideline into data/processed/details/{event_id}.json."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bpa_app import config, llm
from bpa_app.data import load_catalog
from bpa_app.models import Event, EventDetails
from bpa_app.prompts import extract_details_prompt


def extract(event: Event) -> EventDetails:
    """Send the PDF when the provider accepts it, otherwise the extracted text."""
    if llm.supports_pdf():
        pdf = (config.PDF_DIR / str(event.pdf_file)).read_bytes()
        prompt = extract_details_prompt(event.id, event.title)
        return llm.generate_structured(
            prompt, EventDetails, model=config.MODEL_SMART, pdf=pdf
        )

    text_path = config.TEXT_DIR / f"{event.id}.md"
    if not text_path.exists():
        raise llm.LLMError(
            f"{text_path.name} missing; run scripts/extract_text.py first"
        )
    prompt = extract_details_prompt(
        event.id, event.title, text_path.read_text(encoding="utf-8")
    )
    return llm.generate_structured(prompt, EventDetails, model=config.MODEL_SMART)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-extract existing files"
    )
    parser.add_argument("--only", help="comma-separated event ids, e.g. 430,V02")
    parser.add_argument(
        "--delay", type=float, default=6.0, help="seconds to sleep between API calls"
    )
    args = parser.parse_args()

    events = [e for e in load_catalog() if e.pdf_file is not None]
    if args.only:
        wanted = [i.strip() for i in args.only.split(",") if i.strip()]
        known = {e.id for e in events}
        if unknown := [i for i in wanted if i not in known]:
            print(f"No catalog event with a local PDF for: {', '.join(unknown)}")
            return 2
        events = [e for e in events if e.id in set(wanted)]

    config.get_api_key()  # fail fast before any work if the key is missing
    config.DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Provider: {config.LLM_PROVIDER} | model: {config.MODEL_SMART}")

    processed = skipped = 0
    failures: dict[str, str] = {}
    made_call = False
    for event in events:
        out_path = config.DETAILS_DIR / f"{event.id}.json"
        if out_path.exists() and not args.force:
            skipped += 1
            continue

        if made_call:
            time.sleep(args.delay)
        made_call = True
        try:
            details = extract(event)
            out_path.write_text(details.model_dump_json(indent=2), encoding="utf-8")
        except (llm.LLMError, OSError) as exc:
            failures[event.id] = str(exc)
            print(f"FAILED {event.id}: {exc}")
            continue
        processed += 1
        print(f"ok {event.id} ({len(details.rubric)} rubric items)")

    print("\nSummary")
    print(f"  Extracted: {processed}")
    print(f"  Skipped (already exist): {skipped}")
    print(f"  Failed: {len(failures)}")
    for event_id, message in failures.items():
        print(f"    - {event_id}: {message}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
