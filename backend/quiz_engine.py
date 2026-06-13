"""Quiz assembly + scoring.

Builds a quiz from the bank, live LLM generation, or a mix; strips answer/
explanation fields before sending questions to the frontend; and scores the
submitted answers (with per-question timing tracked client-side).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from . import llm_client, mcq_bank


# Cap live-generation retries so we don't exhaust free-tier API quotas while
# trying to fill a shortfall of valid questions.
MAX_LIVE_ATTEMPTS = 4


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _friendly_llm_error(exc: Exception) -> str:
    """Short, exam-safe summary of an LLM failure (hides raw provider dumps)."""
    text = str(exc).lower()
    if "429" in text or "quota" in text or "rate limit" in text or "rate-limit" in text:
        return "The AI's free-tier limit was reached, so new questions couldn't be generated."
    if "api key" in text or "401" in text or "403" in text or "permission" in text:
        return "The AI couldn't be reached (check your API key in Settings)."
    return "AI question generation is unavailable right now."


def _subject_of(q: Dict[str, Any]) -> str:
    """Subject of a question, tolerating the legacy ``category`` field."""
    return str(q.get("subject") or q.get("category") or "General")


def _strip_for_client(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove correct answers/explanations before the quiz is displayed."""
    safe = []
    for q in questions:
        subject = _subject_of(q)
        safe.append(
            {
                "id": q["id"],
                "question": q["question"],
                "options": q["options"],
                "subject": subject,
                "category": subject,
                "topic": q.get("topic", ""),
                "difficulty": q.get("difficulty", "medium"),
            }
        )
    return safe


def build_quiz(
    mode: str,
    num_questions: int,
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    duration_minutes: int = 15,
    provider: str = "groq",
    api_key: str = "",
    topics: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Assemble a quiz.

    ``category`` is the SSC CGL subject ("All" for a full mock). ``topics``
    optionally restricts to specific subtopics within that subject (empty/None
    = all topics).

    Returns ``{quiz_id, duration_minutes, questions, answer_key, warnings}``.
    ``questions`` is client-safe; ``answer_key`` (keyed by question id) stays
    server-side and is used by :func:`score_quiz`.
    """
    mode = (mode or "bank").lower()
    topics = [t for t in (topics or []) if t]
    warnings: List[str] = []
    questions: List[Dict[str, Any]] = []
    # Freshly AI-generated questions (full schema) so the caller can persist
    # them to the writable bank instead of discarding them after the quiz.
    generated_questions: List[Dict[str, Any]] = []

    bank_count = num_questions
    live_count = 0
    bank_source = "bank"
    if mode == "live":
        bank_count, live_count = 0, num_questions
    elif mode == "pdf":
        bank_source = "pdf"

    # --- Bank portion ---
    if bank_count > 0:
        for q in mcq_bank.sample_questions(bank_count, category, difficulty, topics, source=bank_source):
            item = dict(q)
            item["id"] = _new_id()
            item["origin"] = "bank"
            questions.append(item)

    # --- Live portion ---
    if live_count > 0:
        subject_hint = category if category and category != "All" else "SSC CGL"
        gen_category = subject_hint
        try:
            # Keep live generation lightweight: rely on the SSC CGL-specific
            # prompt/topic guidance instead of loading the local embedding/RAG
            # stack, which can add hundreds of MB of resident memory.
            context: List[str] = []
            # Small free-tier models often return fewer valid items than asked,
            # so retry for the shortfall (deduping) up to a capped number of
            # attempts to avoid burning the free API quota.
            collected: List[Dict[str, Any]] = []
            seen: set = set()
            attempts = 0
            max_attempts = max(2, min(MAX_LIVE_ATTEMPTS, live_count))
            while len(collected) < live_count and attempts < max_attempts:
                attempts += 1
                need = live_count - len(collected)
                generated = llm_client.generate_mcqs(
                    context_chunks=context,
                    num_questions=need,
                    category=gen_category,
                    difficulty=difficulty,
                    provider=provider,
                    api_key=api_key,
                    topics=topics,
                )
                new_this_round = 0
                for q in generated:
                    key = q["question"].strip().lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(q)
                    new_this_round += 1
                    if len(collected) >= live_count:
                        break
                # If a round adds nothing new, stop early (model is repeating).
                if new_this_round == 0:
                    break

            for q in collected[:live_count]:
                item = dict(q)
                item["id"] = _new_id()
                item["origin"] = "live"
                questions.append(item)
                generated_questions.append(dict(q))

            shortfall = live_count - len(collected)
            if shortfall > 0:
                # Top up from the bank so the user gets the full count requested.
                topped = 0
                for q in mcq_bank.sample_questions(shortfall, category, difficulty, topics):
                    item = dict(q)
                    item["id"] = _new_id()
                    item["origin"] = "bank-topup"
                    questions.append(item)
                    topped += 1
                if topped:
                    warnings.append(
                        f"AI returned {len(collected)} of {live_count} after {attempts} "
                        f"attempt(s); added {topped} from the question bank."
                    )
                else:
                    warnings.append(
                        f"AI returned {len(collected)} of {live_count} after {attempts} "
                        f"attempt(s); no bank questions available to top up."
                    )
        except llm_client.LLMError as exc:
            warnings.append(f"{_friendly_llm_error(exc)} Using the question bank instead.")
            shortfall = live_count
            for q in mcq_bank.sample_questions(shortfall, category, difficulty, topics):
                item = dict(q)
                item["id"] = _new_id()
                item["origin"] = "bank-fallback"
                questions.append(item)

    if not questions:
        warnings.append("No questions could be assembled for the selected filters.")

    answer_key = {
        q["id"]: {
            "correct_index": q["correct_index"],
            "category": _subject_of(q),
            "subject": _subject_of(q),
            "topic": q.get("topic", ""),
            "difficulty": q.get("difficulty", "medium"),
            "explanation": q.get("explanation", ""),
            "question": q["question"],
            "options": q["options"],
        }
        for q in questions
    }

    return {
        "quiz_id": _new_id(),
        "duration_minutes": duration_minutes,
        "questions": _strip_for_client(questions),
        "answer_key": answer_key,
        "warnings": warnings,
        "generated_questions": generated_questions,
    }


def score_quiz(
    answer_key: Dict[str, Any],
    responses: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score submitted responses.

    ``responses``: list of ``{id, selected_index|None, time_spent_seconds}``.
    Returns overall + per-category stats plus per-question review data.
    """
    by_id = {r.get("id"): r for r in responses}
    total = len(answer_key)
    correct = 0
    attempted = 0
    total_time = 0.0
    category_stats: Dict[str, Dict[str, int]] = {}
    difficulty_stats: Dict[str, Dict[str, int]] = {}
    topic_stats: Dict[str, Dict[str, int]] = {}
    review: List[Dict[str, Any]] = []

    for qid, key in answer_key.items():
        resp = by_id.get(qid, {})
        selected = resp.get("selected_index")
        time_spent = float(resp.get("time_spent_seconds") or 0)
        total_time += time_spent
        is_attempted = selected is not None
        is_correct = is_attempted and int(selected) == int(key["correct_index"])
        if is_attempted:
            attempted += 1
        if is_correct:
            correct += 1

        cat = key.get("category", "General")
        stats = category_stats.setdefault(cat, {"correct": 0, "total": 0})
        stats["total"] += 1
        if is_correct:
            stats["correct"] += 1

        diff = key.get("difficulty", "medium")
        dstats = difficulty_stats.setdefault(diff, {"correct": 0, "total": 0})
        dstats["total"] += 1
        if is_correct:
            dstats["correct"] += 1

        topic = key.get("topic") or "General"
        tstats = topic_stats.setdefault(topic, {"correct": 0, "total": 0})
        tstats["total"] += 1
        if is_correct:
            tstats["correct"] += 1

        review.append(
            {
                "id": qid,
                "question": key["question"],
                "options": key["options"],
                "correct_index": key["correct_index"],
                "selected_index": selected,
                "is_correct": is_correct,
                "attempted": is_attempted,
                "category": cat,
                "topic": key.get("topic", ""),
                "difficulty": key.get("difficulty", "medium"),
                "explanation": key.get("explanation", ""),
                "time_spent_seconds": round(time_spent, 1),
            }
        )

    category_accuracy = {
        cat: {
            "correct": s["correct"],
            "total": s["total"],
            "accuracy": round(100 * s["correct"] / s["total"], 1) if s["total"] else 0.0,
        }
        for cat, s in category_stats.items()
    }

    topic_accuracy = {
        t: {
            "correct": s["correct"],
            "total": s["total"],
            "accuracy": round(100 * s["correct"] / s["total"], 1) if s["total"] else 0.0,
        }
        for t, s in topic_stats.items()
    }

    # Always report the three canonical difficulty buckets, in order.
    difficulty_accuracy = {}
    for level in ("easy", "medium", "hard"):
        s = difficulty_stats.get(level, {"correct": 0, "total": 0})
        difficulty_accuracy[level] = {
            "correct": s["correct"],
            "total": s["total"],
            "accuracy": round(100 * s["correct"] / s["total"], 1) if s["total"] else 0.0,
        }

    return {
        "score": correct,
        "total": total,
        "attempted": attempted,
        "skipped": total - attempted,
        "accuracy": round(100 * correct / total, 1) if total else 0.0,
        "total_time_seconds": round(total_time, 1),
        "avg_time_seconds": round(total_time / total, 1) if total else 0.0,
        "category_accuracy": category_accuracy,
        "difficulty_accuracy": difficulty_accuracy,
        "topic_accuracy": topic_accuracy,
        "review": review,
    }
