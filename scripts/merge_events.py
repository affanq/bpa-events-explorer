"""Merge catalog.json + details/*.json + text/ existence into data/processed/events.json."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import TypeAdapter, ValidationError

from bpa_app import config
from bpa_app.data import load_catalog, mentions_testing
from bpa_app.models import Event, EventDetails


def main() -> int:
    events: list[Event] = []
    notes: list[str] = []
    invalid: list[str] = []

    for event in load_catalog():
        details_path = config.DETAILS_DIR / f"{event.id}.json"
        details: EventDetails | None = None
        if details_path.exists():
            try:
                details = EventDetails.model_validate_json(details_path.read_bytes())
            except ValidationError:
                invalid.append(event.id)

        if (
            event.format == "Virtual"
            and details is not None
            and "Testing" not in event.event_type
            and (phrase := mentions_testing(details))
        ):
            notes.append(
                f"{event.id}: details mention a testing component ({phrase!r}); "
                f"keeping catalog event_type {event.event_type}"
            )

        events.append(
            event.model_copy(
                update={
                    "has_text": (config.TEXT_DIR / f"{event.id}.md").exists(),
                    "details": details,
                }
            )
        )

    config.EVENTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    config.EVENTS_JSON.write_bytes(TypeAdapter(list[Event]).dump_json(events, indent=2))

    print(f"Wrote {len(events)} events to {config.EVENTS_JSON}")
    print(f"  With text: {sum(e.has_text for e in events)}")
    print(f"  With details: {sum(e.details is not None for e in events)}")
    if invalid:
        print(f"  Invalid details files ignored: {', '.join(invalid)}")
    for note in notes:
        print(f"NOTE {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
