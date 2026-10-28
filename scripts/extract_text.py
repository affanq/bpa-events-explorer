"""Extract guideline PDF text to data/processed/text/{event_id}.md."""

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf

from bpa_app.config import PDF_DIR, TEXT_DIR
from bpa_app.data import load_catalog
from bpa_app.models import Event

MIN_CHARS = 500
TOP_MARGIN = 0.07  # fraction of page height treated as header zone
BOTTOM_MARGIN = 0.90  # y fraction where the footer zone starts
MIN_BOILERPLATE_LETTERS = 20
MIN_BOILERPLATE_DOCS = 3  # margin text shared by this many PDFs is boilerplate

_HYPHEN_BREAK = re.compile(r"(?<=[A-Za-z])-\n(?=[a-z])")
_LONE_BULLET = re.compile(r"^([•●▪◦■])\n(?=\S)", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")


@dataclass
class Block:
    text: str
    in_margin: bool


Pages = list[list[Block]]


def read_pages(pdf_path: Path) -> Pages:
    pages: Pages = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            height = page.rect.height
            pages.append(
                [
                    Block(
                        b[4],
                        b[3] < TOP_MARGIN * height or b[1] > BOTTOM_MARGIN * height,
                    )
                    for b in page.get_text("blocks")
                    if b[6] == 0  # text blocks only
                ]
            )
    return pages


def _letters(text: str) -> str:
    # Letters only: ignores page numbers and the varying line wrapping of headers/footers.
    return re.sub(r"[^a-z]", "", text.lower())


def _margin_letters(pages: Pages) -> set[str]:
    return {
        letters
        for blocks in pages
        for b in blocks
        if b.in_margin and len(letters := _letters(b.text)) >= MIN_BOILERPLATE_LETTERS
    }


def find_shared_boilerplate(docs: list[Pages]) -> set[str]:
    """Margin blocks that repeat across several PDFs (covers single-page PDFs)."""
    counts = Counter(letters for pages in docs for letters in _margin_letters(pages))
    return {k for k, n in counts.items() if n >= MIN_BOILERPLATE_DOCS}


def drop_repeated_margins(pages: Pages, shared: set[str]) -> list[str]:
    """Return per-page body text without headers/footers."""
    page_keys = [
        _letters("".join(b.text for b in blocks if b.in_margin)) for blocks in pages
    ]

    def is_boilerplate(block: Block, page_index: int) -> bool:
        if not block.in_margin:
            return False
        if not block.text.strip():
            return True
        letters = _letters(block.text)
        if len(letters) < MIN_BOILERPLATE_LETTERS:
            return False
        return any(letters in k or k in letters for k in shared) or any(
            letters in k for i, k in enumerate(page_keys) if i != page_index
        )

    return [
        "".join(b.text for b in blocks if not is_boilerplate(b, i))
        for i, blocks in enumerate(pages)
    ]


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u00ad", "")
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _HYPHEN_BREAK.sub("", text)
    text = _LONE_BULLET.sub(r"\1 ", text)
    return _BLANK_RUN.sub("\n\n", text).strip()


def build_markdown(event: Event, page_texts: list[str]) -> str:
    lines = [f"# {event.title}", "", f"- Event ID: {event.id}"]
    if source := event.view_url or event.download_url:
        lines.append(f"- Source: {source}")
    sections = [
        f"## Page {number}\n\n{text}"
        for number, text in enumerate(page_texts, start=1)
        if text
    ]
    return "\n".join(lines) + "\n\n" + "\n\n".join(sections) + "\n"


def body_length(markdown: str) -> int:
    start = markdown.find("## Page")
    return 0 if start < 0 else len(markdown) - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-extract existing files"
    )
    args = parser.parse_args()

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    written = skipped = total_chars = 0
    warnings: list[str] = []

    events = [e for e in load_catalog() if e.pdf_file is not None]
    docs: dict[str, Pages] = {}
    for event in events:
        try:
            docs[event.id] = read_pages(PDF_DIR / str(event.pdf_file))
        except (pymupdf.FileDataError, RuntimeError) as exc:
            warnings.append(f"{event.id}: could not read {event.pdf_file} ({exc})")
    shared = find_shared_boilerplate(list(docs.values()))

    for event in events:
        if event.id not in docs:
            continue
        out_path = TEXT_DIR / f"{event.id}.md"
        if out_path.exists() and not args.force:
            markdown = out_path.read_text(encoding="utf-8")
            skipped += 1
        else:
            texts = [
                clean_text(t) for t in drop_repeated_margins(docs[event.id], shared)
            ]
            markdown = build_markdown(event, texts)
            out_path.write_text(markdown, encoding="utf-8")
            written += 1

        total_chars += len(markdown)
        if (chars := body_length(markdown)) < MIN_CHARS:
            warnings.append(
                f"{event.id}: only {chars} chars of text in {event.pdf_file} "
                "(likely a scanned/image PDF)"
            )

    print(f"Files written: {written}")
    print(f"Files skipped (already exist): {skipped}")
    print(f"Warnings: {len(warnings)}")
    for warning in warnings:
        print(f"  - {warning}")
    print(f"Total characters (all text files): {total_chars:,}")
    print(f"Rough token estimate (chars/4): {total_chars // 4:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
