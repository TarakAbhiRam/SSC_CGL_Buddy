"""Offline prep — step 1: extract text from source PDFs.

Reads every PDF in ``data/pdfs/`` and writes raw per-page text to
``data/extracted/<pdfname>.json``. Scanned/image-only pages require OCR, which
is currently a stub (run with --ocr to attempt it once wired up).

Usage:
    python scripts/ingest_pdfs.py
    python scripts/ingest_pdfs.py --ocr
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make 'backend' importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import pdf_processor  # noqa: E402
from backend.paths import pdfs_dir, resource_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from source PDFs.")
    parser.add_argument("--ocr", action="store_true", help="Attempt OCR on image-only pages.")
    args = parser.parse_args()

    src = pdfs_dir()
    out_dir = resource_path("data", "extracted")
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(src.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {src}. Add some and re-run.")
        return

    for pdf in pdfs:
        print(f"Extracting {pdf.name} …")
        try:
            pages = list(pdf_processor.extract_pages(pdf, use_ocr=args.ocr))
        except pdf_processor.OCRNotConfigured as exc:
            print(f"  ! {exc}")
            print("  Skipping (run with OCR wired up to handle scanned pages).")
            continue
        non_empty = sum(1 for p in pages if p["text"])
        (out_dir / f"{pdf.stem}.json").write_text(
            json.dumps({"source_pdf": pdf.name, "pages": pages}, indent=2),
            encoding="utf-8",
        )
        print(f"  -> {len(pages)} pages ({non_empty} with text)")

    print(f"Done. Extracted text in {out_dir}")


if __name__ == "__main__":
    main()
