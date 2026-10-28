"""Build data/processed/catalog.json from the Excel workbook, PDF link CSV and local PDFs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Any

import pandas as pd
from pydantic import TypeAdapter

from bpa_app.config import CATALOG_JSON, PDF_DIR, SOURCE_DIR
from bpa_app.data import (
    NormalizationError,
    clean_str,
    normalize_division,
    normalize_participation,
    normalize_type,
    parse_bool,
)
from bpa_app.models import Event

WORKBOOK = SOURCE_DIR / "BPA Event Requirements 2026-2027.xlsx"
LINKS_CSV = SOURCE_DIR / "bpa_event_pdf_links.csv"

SHEET_FORMATS = {
    "IndividualTeam": "In-Person",
    "Virtual": "Virtual",
    "Open Events": "Open",
}
EXPECTED_COUNTS = {"IndividualTeam": 82, "Virtual": 16, "Open Events": 15}

Row = dict[str, Any]


def load_links() -> dict[str, tuple[str | None, str | None]]:
    """Map trimmed event id -> (view_url, download_url)."""
    df = pd.read_csv(LINKS_CSV, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    links: dict[str, tuple[str | None, str | None]] = {}
    for row in df.to_dict("records"):
        event_id = clean_str(row.get("Event #"))
        if event_id:
            links[event_id] = (
                clean_str(row.get("View URL")),
                clean_str(row.get("Direct Download URL")),
            )
    return links


def find_local_pdfs() -> dict[str, str]:
    """Map event id (filename prefix before the first underscore) -> PDF filename."""
    pdfs: dict[str, str] = {}
    for path in sorted(PDF_DIR.glob("*.pdf")):
        pdfs.setdefault(path.name.split("_", 1)[0], path.name)
    return pdfs


def read_sheet(name: str) -> list[Row]:
    df = pd.read_excel(WORKBOOK, sheet_name=name, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.map(clean_str).dropna(how="all")
    return df.to_dict("records")


def _required(row: Row, column: str, event_id: str) -> str:
    value = clean_str(row.get(column))
    if value is None:
        raise NormalizationError(f"Event {event_id}: missing {column}")
    return value


def build_event(
    sheet: str,
    row: Row,
    links: dict[str, tuple[str | None, str | None]],
    pdfs: dict[str, str],
) -> Event:
    event_id = clean_str(row.get("Event #"))
    if event_id is None:
        raise NormalizationError(f"{sheet}: row without an Event #: {row}")

    if sheet == "Virtual":
        subject = "Virtual"
        # In this sheet "Type" holds Individual/Team; events are project-based.
        participation = normalize_participation(row.get("Type"), event_id)
        event_type = ["Judged"]
    else:
        subject = _required(row, "Subject", event_id)
        participation = normalize_participation(row.get("Individual or Team"), event_id)
        event_type = normalize_type(row.get("Type"), event_id)

    view_url, download_url = links.get(event_id, (None, None))
    return Event(
        id=event_id,
        title=_required(row, "Title", event_id),
        subject=subject,
        format=SHEET_FORMATS[sheet],
        participation=participation,
        event_type=event_type,
        divisions=normalize_division(row.get("Division"), event_id),
        certification=parse_bool(row.get("Certification"), event_id),
        presubmit=parse_bool(row.get("Presubmit"), event_id),
        # Virtual deadlines are blank in the source and deliberately not mapped.
        regional_deadline=clean_str(row.get("Regional Submission Deadline")),
        nlc_deadline=clean_str(row.get("NLC Presubmit Deadline")),
        view_url=view_url,
        download_url=download_url,
        pdf_file=pdfs.get(event_id),
        has_text=False,
        details=None,
    )


def main() -> int:
    links = load_links()
    pdfs = find_local_pdfs()

    events: list[Event] = []
    counts: dict[str, int] = {}
    problems: list[str] = []
    for sheet in SHEET_FORMATS:
        counts[sheet] = 0
        for row in read_sheet(sheet):
            try:
                events.append(build_event(sheet, row, links, pdfs))
            except NormalizationError as exc:
                problems.append(f"[{sheet}] {exc}")
            else:
                counts[sheet] += 1

    seen: set[str] = set()
    for event in events:
        if event.id in seen:
            problems.append(f"Duplicate event id {event.id}")
        seen.add(event.id)

    CATALOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_JSON.write_bytes(TypeAdapter(list[Event]).dump_json(events, indent=2))

    print(f"Wrote {len(events)} events to {CATALOG_JSON}")
    for sheet, count in counts.items():
        print(f"  {sheet}: {count} (expected {EXPECTED_COUNTS[sheet]})")
    print(f"  Total: {len(events)} (expected {sum(EXPECTED_COUNTS.values())})")

    no_link = [e.id for e in events if not (e.view_url or e.download_url)]
    no_pdf = [e.id for e in events if e.pdf_file is None]
    print(f"Events without a link ({len(no_link)}): {', '.join(no_link) or '-'}")
    print(f"Events without a local PDF ({len(no_pdf)}): {', '.join(no_pdf) or '-'}")
    print(f"Unrecognized values / problems ({len(problems)}):")
    for problem in problems:
        print(f"  - {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
