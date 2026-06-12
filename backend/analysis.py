"""Post-quiz analysis helpers.

Most aggregation happens in :func:`backend.quiz_engine.score_quiz`. This module
shapes that result for the charts/tables on the analysis screen and can
optionally enrich review items with LLM-generated explanations when a bank
question shipped without one.
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_charts(scored: Dict[str, Any]) -> Dict[str, Any]:
    """Produce Chart.js-friendly series from a scored result."""
    cat_acc = scored.get("category_accuracy", {})
    categories = list(cat_acc.keys())
    accuracy_series = [cat_acc[c]["accuracy"] for c in categories]
    correct_series = [cat_acc[c]["correct"] for c in categories]
    total_series = [cat_acc[c]["total"] for c in categories]

    review = scored.get("review", [])
    time_labels = [f"Q{i + 1}" for i in range(len(review))]
    time_series = [r.get("time_spent_seconds", 0) for r in review]
    correctness = [bool(r.get("is_correct")) for r in review]

    # Difficulty distribution + accuracy (easy / medium / hard).
    diff_acc = scored.get("difficulty_accuracy", {})
    diff_levels = ["easy", "medium", "hard"]
    diff_labels = ["Easy", "Moderate", "Hard"]
    diff_total = [diff_acc.get(l, {}).get("total", 0) for l in diff_levels]
    diff_correct = [diff_acc.get(l, {}).get("correct", 0) for l in diff_levels]
    diff_wrong = [
        diff_acc.get(l, {}).get("total", 0) - diff_acc.get(l, {}).get("correct", 0)
        for l in diff_levels
    ]
    diff_accuracy = [diff_acc.get(l, {}).get("accuracy", 0.0) for l in diff_levels]

    return {
        "category_accuracy": {
            "labels": categories,
            "accuracy": accuracy_series,
            "correct": correct_series,
            "total": total_series,
        },
        "time_per_question": {
            "labels": time_labels,
            "seconds": time_series,
            "correct": correctness,
        },
        "difficulty": {
            "labels": diff_labels,
            "total": diff_total,
            "correct": diff_correct,
            "wrong": diff_wrong,
            "accuracy": diff_accuracy,
        },
    }


def summarize(scored: Dict[str, Any]) -> Dict[str, Any]:
    """Headline numbers for the top of the analysis screen."""
    return {
        "score": scored.get("score", 0),
        "total": scored.get("total", 0),
        "accuracy": scored.get("accuracy", 0.0),
        "attempted": scored.get("attempted", 0),
        "skipped": scored.get("skipped", 0),
        "total_time_seconds": scored.get("total_time_seconds", 0.0),
        "avg_time_seconds": scored.get("avg_time_seconds", 0.0),
    }


def enrich_explanations(
    review: List[Dict[str, Any]],
    provider: str,
    api_key: str,
) -> List[Dict[str, Any]]:
    """Fill in missing explanations via the LLM (best-effort, non-fatal)."""
    from . import llm_client

    missing = [r for r in review if not r.get("explanation")]
    if not missing or not api_key:
        return review

    for item in missing:
        prompt = (
            "Explain in 1-2 sentences why the correct answer is right.\n"
            f"Question: {item['question']}\n"
            f"Options: {item['options']}\n"
            f"Correct option index (0-based): {item['correct_index']}\n"
            'Return ONLY JSON: [{"question":"...","options":["a","b","c","d"],'
            '"correct_index":0,"category":"x","difficulty":"easy","explanation":"..."}]'
        )
        try:
            raw = llm_client._call_provider(prompt, provider, api_key)  # noqa: SLF001
            parsed = llm_client.parse_mcqs(raw)
            if parsed and parsed[0].get("explanation"):
                item["explanation"] = parsed[0]["explanation"]
        except llm_client.LLMError:
            continue
    return review
