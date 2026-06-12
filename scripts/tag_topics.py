"""Offline prep — step 3: tag chunks with topic + difficulty via one LLM pass.

Updates the metadata of every chunk in the bundled ChromaDB store with a
``topic_tag`` and ``difficulty``, using the dev's own API key. Run once after
chunk_and_embed.py.

Requires an API key in your local config (run the app's Settings once, or set
the GROQ_API_KEY / GEMINI_API_KEY environment variable).

Usage:
    python scripts/tag_topics.py --provider groq
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, llm_client, vector_store  # noqa: E402

# Edit this list to match your exam's syllabus.
TOPICS = [
    "General Knowledge", "Quantitative Aptitude", "English Language",
    "Reasoning", "Current Affairs", "History", "Geography",
    "Polity", "Economics", "Science",
]


def classify(text: str, provider: str, api_key: str) -> dict:
    prompt = (
        "Classify the following SSC study text. "
        f"Pick the single best topic from this list: {TOPICS}. "
        'Return ONLY JSON: [{"question":"x","options":["a","b","c","d"],'
        '"correct_index":0,"category":"<one topic from the list>",'
        '"difficulty":"easy|medium|hard","explanation":"x"}].\n\n'
        f"Text:\n{text[:1500]}"
    )
    try:
        raw = llm_client._call_provider(prompt, provider, api_key)  # noqa: SLF001
        parsed = llm_client.parse_mcqs(raw)
        if parsed:
            return {
                "topic_tag": parsed[0].get("category", "General Knowledge"),
                "difficulty": parsed[0].get("difficulty", "medium"),
            }
    except llm_client.LLMError as exc:
        print(f"  ! classify failed: {exc}")
    return {"topic_tag": "General Knowledge", "difficulty": "medium"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Tag chunks with topic + difficulty.")
    parser.add_argument("--provider", default=None, help="groq or gemini")
    args = parser.parse_args()

    cfg = config.load_config()
    provider = args.provider or cfg.get("active_provider", "groq")
    api_key = (
        config.get_api_key(provider)
        or os.environ.get(f"{provider.upper()}_API_KEY", "")
    ).strip()
    if not api_key:
        print(f"No {provider} API key. Set it in the app Settings or {provider.upper()}_API_KEY env var.")
        return

    collection = vector_store._get_bundled_collection()  # noqa: SLF001
    data = collection.get(include=["documents", "metadatas"])
    ids = data.get("ids", [])
    docs = data.get("documents", [])
    metas = data.get("metadatas", [])
    if not ids:
        print("No chunks in the bundled store. Run chunk_and_embed.py first.")
        return

    print(f"Tagging {len(ids)} chunks via {provider} …")
    new_metas = []
    for i, (doc, meta) in enumerate(zip(docs, metas)):
        meta = meta or {}
        tags = classify(doc, provider, api_key)
        meta.update(tags)
        new_metas.append(meta)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(ids)}")

    collection.update(ids=ids, metadatas=new_metas)
    print("Done. Chunk metadata updated with topic_tag + difficulty.")


if __name__ == "__main__":
    main()
