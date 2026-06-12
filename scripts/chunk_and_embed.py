"""Offline prep — step 2: chunk extracted text + embed into the bundled store.

Reads ``data/extracted/*.json`` (from ingest_pdfs.py), chunks each page, embeds
with all-MiniLM-L6-v2, and writes vectors + metadata into the bundled ChromaDB
at ``data/chroma_db/``. This index is shipped with the app.

Usage:
    python scripts/chunk_and_embed.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import pdf_processor, vector_store  # noqa: E402
from backend.paths import resource_path  # noqa: E402

BATCH = 128


def _chunk_id(source: str, page: int, index: int, text: str) -> str:
    return hashlib.sha1(f"{source}|{page}|{index}|{text}".encode("utf-8")).hexdigest()[:16]


def main() -> None:
    extracted_dir = resource_path("data", "extracted")
    files = sorted(extracted_dir.glob("*.json"))
    if not files:
        print(f"No extracted text in {extracted_dir}. Run ingest_pdfs.py first.")
        return

    # Build chunks across all files.
    chunks = []
    skipped = 0
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        source = data["source_pdf"]
        page_texts = [p["text"] for p in data["pages"]]
        boilerplate = pdf_processor._detect_boilerplate(page_texts)
        for page in data["pages"]:
            cleaned = pdf_processor.clean_text(page["text"], boilerplate)
            for i, chunk in enumerate(pdf_processor.chunk_text(cleaned)):
                content_type = pdf_processor.classify_chunk(chunk)
                if content_type is None:
                    skipped += 1
                    continue
                chunks.append({
                    "id": _chunk_id(source, page["page_number"], i, chunk),
                    "text": chunk,
                    "metadata": {
                        "source_pdf": source,
                        "page_number": page["page_number"],
                        "content_type": content_type,
                        # topic_tag + difficulty filled by tag_topics.py
                    },
                })
    if skipped:
        print(f"Filtered out {skipped} junk/low-quality chunks.")

    if not chunks:
        print("No chunks produced (PDFs may be scanned/empty). Nothing to embed.")
        return

    print(f"Embedding {len(chunks)} chunks into the bundled store …")
    total = 0
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start : start + BATCH]
        total += vector_store.add_chunks(batch, to_user_store=False)
        print(f"  {total}/{len(chunks)}")
    print(f"Done. Vector index written to {resource_path('data', 'chroma_db')}")


if __name__ == "__main__":
    main()
