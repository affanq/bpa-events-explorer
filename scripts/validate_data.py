"""Report gaps and inconsistencies in data/processed/events.json."""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bpa_app.config import EVENTS_JSON
from bpa_app.data import PROBLEM_ORDER, find_problems, load_events

TITLE_WIDTH = 40


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def main() -> int:
    if not EVENTS_JSON.exists():
        print(f"{EVENTS_JSON} not found; run scripts/merge_events.py first")
        return 2

    events = load_events()
    problems = find_problems(events)
    if not problems:
        print(f"No problems found in {len(events)} events.")
        return 0

    rows = [
        (p.event_id, _clip(p.title, TITLE_WIDTH), p.kind, p.detail) for p in problems
    ]
    header = ("Event", "Title", "Problem", "Detail")
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(4)]
    for row in [header, ("-" * w for w in widths), *rows]:
        print(
            "  ".join(
                cell.ljust(w) for cell, w in zip(row, widths, strict=True)
            ).rstrip()
        )

    counts = Counter(p.kind for p in problems)
    print(f"\n{len(problems)} problems across {len(events)} events:")
    for kind in PROBLEM_ORDER:
        print(f"  {kind}: {counts.get(kind, 0)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
