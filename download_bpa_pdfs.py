#!/usr/bin/env python3
"""
Download BPA event guideline PDFs listed in bpa_event_pdf_links.csv.

Usage:
    pip install requests
    python download_bpa_pdfs.py                      # uses defaults
    python download_bpa_pdfs.py --csv my.csv --out pdfs

Notes:
- Files must be shared on Google Drive as "Anyone with the link can view".
- Already-downloaded files are skipped, so it is safe to re-run.
- Failures are written to download_failures.csv.
"""
import argparse
import csv
import re
import sys
import time
from pathlib import Path

import requests

DRIVE_URL = "https://drive.google.com/uc?export=download&id={id}"


def safe_name(event_no: str, title: str) -> str:
    name = f"{event_no.strip()}_{title.strip()}"
    name = re.sub(r"[^\w\-]+", "_", name)          # replace spaces, /, &, etc.
    return re.sub(r"_+", "_", name).strip("_") + ".pdf"


def download(session: requests.Session, file_id: str) -> bytes:
    resp = session.get(DRIVE_URL.format(id=file_id), timeout=60)
    resp.raise_for_status()

    # Large files show a "can't scan for viruses" page; follow its confirm link.
    if b"%PDF" not in resp.content[:1024]:
        token = re.search(r'name="confirm" value="([^"]+)"', resp.text)
        uuid = re.search(r'name="uuid" value="([^"]+)"', resp.text)
        if token:
            params = {"id": file_id, "export": "download", "confirm": token.group(1)}
            if uuid:
                params["uuid"] = uuid.group(1)
            resp = session.get("https://drive.usercontent.google.com/download",
                               params=params, timeout=60)
            resp.raise_for_status()

    if b"%PDF" not in resp.content[:1024]:
        raise ValueError("Response is not a PDF (file may not be publicly shared)")
    return resp.content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="bpa_event_pdf_links.csv")
    ap.add_argument("--out", default="pdfs")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between downloads")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (BPA event downloader)"

    ok = skipped = 0
    failures = []

    for i, row in enumerate(rows, 1):
        event_no, title, file_id = row["Event #"], row["Title"], row["File ID"].strip()
        label = f"[{i}/{len(rows)}] {event_no} {title}"

        if not file_id:
            print(f"{label}: no link - skipped")
            failures.append({**row, "Error": "No link in spreadsheet"})
            continue

        dest = out_dir / safe_name(event_no, title)
        if dest.exists() and dest.stat().st_size > 0:
            print(f"{label}: already downloaded")
            skipped += 1
            continue

        try:
            data = download(session, file_id)
            dest.write_bytes(data)
            ok += 1
            print(f"{label}: OK ({len(data) // 1024} KB)")
        except Exception as e:  # noqa: BLE001
            print(f"{label}: FAILED - {e}")
            failures.append({**row, "Error": str(e)})

        time.sleep(args.delay)

    if failures:
        with open("download_failures.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(failures[0].keys()))
            w.writeheader()
            w.writerows(failures)

    print(f"\nDone: {ok} downloaded, {skipped} skipped, {len(failures)} failed")
    if failures:
        print("See download_failures.csv for details.")
    return 1 if any(r["File ID"] for r in failures) else 0


if __name__ == "__main__":
    sys.exit(main())
