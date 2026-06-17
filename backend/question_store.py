"""Writable store of structured MCQs (separate from the read-only bundled bank).

The bundled ``data/mcq_bank.json`` ships inside the app and is read-only (it
may live in a frozen/immutable bundle). This module keeps a *writable* pool of
questions in the per-user app-data dir so the app can grow its own question
bank over time — chiefly by saving the MCQs the AI generates during live
quizzes (so they are never wasted), with duplicate detection.

Each record uses the same schema as the bundled bank:
``{question, options, correct_index, subject, topic, difficulty, explanation}``
plus bookkeeping fields ``{id, source, added_at}``.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from . import syllabus
from .paths import user_data_dir

_LOCK = threading.Lock()

# Cap the writable pool so the file never grows without bound.
MAX_QUESTIONS = 5000
EXPORT_FORMAT = "cgl-buddy-mcq-db"
EXPORT_VERSION = 1


def _store_path():
    return user_data_dir() / "user_mcq.json"


def normalize_question(text: str) -> str:
    """Canonical form of a question used for duplicate detection."""
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)  # drop punctuation so trivial diffs collapse
    return s.strip()


def _key(text: str) -> str:
    return hashlib.sha1(normalize_question(text).encode("utf-8")).hexdigest()[:16]


def _read() -> List[Dict[str, Any]]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write(questions: List[Dict[str, Any]]) -> None:
    path = _store_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(questions, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def list_questions(
    subject: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Stored questions, optionally filtered by subject and/or source."""
    out = _read()
    if subject and subject != "All":
        out = [q for q in out if (q.get("subject") or q.get("category")) == subject]
    if source and source != "All":
        out = [q for q in out if q.get("source") == source]
    return out


def all_questions() -> List[Dict[str, Any]]:
    """Every stored question (used when merging with the bundled bank)."""
    return _read()


def export_payload() -> Dict[str, Any]:
    """Portable JSON payload containing the user's writable questions only."""
    questions = []
    for q in _read():
        questions.append({
            "question": q.get("question", ""),
            "options": q.get("options", []),
            "correct_index": q.get("correct_index"),
            "subject": q.get("subject") or q.get("category") or "General",
            "topic": q.get("topic", ""),
            "difficulty": q.get("difficulty", "medium"),
            "explanation": q.get("explanation", ""),
            "source": q.get("source") or "Imported database",
        })
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "question_count": len(questions),
        "questions": questions,
    }


def records_from_payload(payload: Any) -> List[Dict[str, Any]]:
    """Extract MCQ records from either app-export JSON or a bare MCQ list."""
    records = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Database JSON must be a list of questions or contain a questions array.")
    return [r for r in records if isinstance(r, dict)]


def collapse_ai_sources() -> int:
    """Relabel legacy per-subject AI sources (e.g. "AI generated · Quant")
    to a single "AI generated" tag. Returns the number of records changed."""
    with _LOCK:
        questions = _read()
        changed = 0
        for q in questions:
            src = q.get("source") or ""
            if src.startswith("AI generated") and src != "AI generated":
                q["source"] = "AI generated"
                changed += 1
        if changed:
            _write(questions)
        return changed


def _canonical_subject(raw: str) -> str:
    text = (raw or "").strip().lower()
    aliases = {
        "reasoning": syllabus.REASONING,
        "general intelligence": syllabus.REASONING,
        "general intelligence & reasoning": syllabus.REASONING,
        "quant": syllabus.QUANT,
        "math": syllabus.QUANT,
        "mathematics": syllabus.QUANT,
        "quantitative aptitude": syllabus.QUANT,
        "english": syllabus.ENGLISH,
        "english comprehension": syllabus.ENGLISH,
        "general awareness": syllabus.GA,
        "gk": syllabus.GA,
        "ga": syllabus.GA,
    }
    return aliases.get(text, raw or "General")


def _infer_topic(subject: str, question: str) -> str:
    q = (question or "").lower()
    if subject == syllabus.ENGLISH:
        if any(k in q for k in ("rearrange", "correct sequence", "arrange the following", "para", "sentence order")):
            return "Para Jumbles (Sentence Rearrangement)"
        if any(k in q for k in ("read the passage", "according to the passage", "passage", "comprehension")):
            return "Reading Comprehension"
        if "synonym" in q:
            return "Synonyms"
        if "antonym" in q:
            return "Antonyms"
        if "idiom" in q or "phrase" in q:
            return "Idioms & Phrases"
    return ""


def retag_ai_questions() -> int:
    """Backfill canonical subject/topic tags for stored AI questions.

    This is best-effort and intentionally conservative: only missing/legacy
    fields are updated.
    """
    with _LOCK:
        questions = _read()
        changed = 0
        for q in questions:
            src = str(q.get("source") or "")
            if not src.startswith("AI generated"):
                continue

            subject_old = str(q.get("subject") or q.get("category") or "General")
            subject_new = _canonical_subject(subject_old)
            if subject_new != subject_old:
                q["subject"] = subject_new
                changed += 1

            topic_old = str(q.get("topic") or "").strip()
            if not topic_old:
                inferred = _infer_topic(subject_new, str(q.get("question") or ""))
                if inferred:
                    q["topic"] = inferred
                    changed += 1

        if changed:
            _write(questions)
        return changed


def sources() -> List[Dict[str, Any]]:
    """Distinct sources with question counts, newest activity first."""
    counts: Dict[str, int] = {}
    for q in _read():
        src = q.get("source") or "Unknown"
        counts[src] = counts.get(src, 0) + 1
    return [{"source": s, "count": n} for s, n in sorted(counts.items())]


def _existing_keys(extra: Optional[Iterable[str]] = None) -> Set[str]:
    """Keys already present in this store (plus any caller-supplied extras)."""
    keys = {_key(q.get("question", "")) for q in _read()}
    if extra:
        keys.update(extra)
    return keys


def add_questions(
    records: List[Dict[str, Any]],
    source: str = "AI generated",
) -> Dict[str, int]:
    """Add new MCQs, skipping duplicates (within the store *and* the bundled bank).

    Returns ``{"added": n, "skipped": m}``.
    """
    if not records:
        return {"added": 0, "skipped": 0}

    # Duplicate check spans the bundled bank too, so AI questions identical to
    # shipped ones aren't re-stored. Imported lazily to avoid a circular import.
    try:
        from . import mcq_bank
        bundled_keys = {_key(q.get("question", "")) for q in mcq_bank.bundled_questions()}
    except Exception:
        bundled_keys = set()

    with _LOCK:
        store = _read()
        seen = {_key(q.get("question", "")) for q in store} | bundled_keys
        added = 0
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()
        for rec in records:
            question = (rec.get("question") or "").strip()
            options = rec.get("options") or []
            try:
                correct_index = int(rec.get("correct_index"))
            except (TypeError, ValueError):
                skipped += 1
                continue
            if not question or len(options) != 4 or correct_index not in range(4):
                skipped += 1
                continue
            k = _key(question)
            if k in seen:
                skipped += 1
                continue
            seen.add(k)
            subject = rec.get("subject") or rec.get("category") or "General"
            store.append({
                "id": uuid.uuid4().hex[:12],
                "question": question,
                "options": options,
                "correct_index": correct_index,
                "subject": subject,
                "topic": rec.get("topic", ""),
                "difficulty": rec.get("difficulty", "medium"),
                "explanation": rec.get("explanation", ""),
                "source": source,
                "added_at": now,
            })
            added += 1
        if added:
            # Trim oldest if we somehow exceed the cap.
            if len(store) > MAX_QUESTIONS:
                store = store[-MAX_QUESTIONS:]
            _write(store)
    return {"added": added, "skipped": skipped}


def delete_by_source(source: str) -> int:
    """Delete all stored questions with the given source. Returns count removed."""
    with _LOCK:
        store = _read()
        keep = [q for q in store if q.get("source") != source]
        removed = len(store) - len(keep)
        if removed:
            _write(keep)
    return removed


def delete_question(question_id: str) -> int:
    """Delete a single stored question by its id. Returns count removed (0 or 1)."""
    if not question_id:
        return 0
    with _LOCK:
        store = _read()
        keep = [q for q in store if q.get("id") != question_id]
        removed = len(store) - len(keep)
        if removed:
            _write(keep)
    return removed


def clear_all() -> int:
    """Delete every stored question. Returns count removed."""
    with _LOCK:
        store = _read()
        removed = len(store)
        _write([])
    return removed
