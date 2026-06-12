"""Offline prep — step 4: pre-generate the shipped MCQ bank.

Walks the tagged chunks per topic, generates MCQs via the LLM, validates them,
and writes a deduplicated pool to ``data/mcq_bank.json``. This is what powers
the no-API-key "bank mode" for end users.

Usage:
    python scripts/build_mcq_bank.py --per-topic 20 --provider groq
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, llm_client, vector_store  # noqa: E402
from backend.paths import bundled_mcq_bank  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-generate the shipped MCQ bank.")
    parser.add_argument("--per-topic", type=int, default=20, help="MCQs to generate per topic.")
    parser.add_argument("--batch", type=int, default=5, help="MCQs per LLM call.")
    parser.add_argument("--provider", default=None, help="groq or gemini")
    args = parser.parse_args()

    cfg = config.load_config()
    provider = args.provider or cfg.get("active_provider", "groq")
    api_key = (
        config.get_api_key(provider)
        or os.environ.get(f"{provider.upper()}_API_KEY", "")
    ).strip()
    if not api_key:
        print(f"No {provider} API key. Set it in Settings or {provider.upper()}_API_KEY env var.")
        return

    categories = vector_store.list_categories(include_user_uploads=False)
    if not categories:
        print("No categories found. Run tag_topics.py first.")
        return

    bank = []
    seen_questions = set()
    for category in categories:
        print(f"Generating for: {category}")
        generated = 0
        while generated < args.per_topic:
            chunks = vector_store.query_chunks(
                query_text=category, top_k=8, category=category
            )
            context = [c["text"] for c in chunks]
            want = min(args.batch, args.per_topic - generated)
            try:
                mcqs = llm_client.generate_mcqs(
                    context_chunks=context,
                    num_questions=want,
                    category=category,
                    difficulty="All",
                    provider=provider,
                    api_key=api_key,
                )
            except llm_client.LLMError as exc:
                print(f"  ! {exc}; skipping rest of this topic.")
                break
            added_this_round = 0
            for m in mcqs:
                key = m["question"].strip().lower()
                if key in seen_questions:
                    continue
                seen_questions.add(key)
                bank.append(m)
                generated += 1
                added_this_round += 1
            print(f"  {generated}/{args.per_topic}")
            if added_this_round == 0:
                break  # avoid infinite loop if model keeps repeating

    out = bundled_mcq_bank()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bank, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Done. Wrote {len(bank)} questions to {out}")


if __name__ == "__main__":
    main()
