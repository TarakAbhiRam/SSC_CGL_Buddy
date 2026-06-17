"""Load + sample/filter the prebuilt MCQ bank shipped with the app.

The bank is a JSON array of MCQs in the same schema produced by
``backend.llm_client.parse_mcqs``. Bank + images mode needs **no API key**.
"""

from __future__ import annotations

import json
import random
import threading
from typing import Any, Dict, List, Optional

from .paths import bundled_mcq_bank

IMAGE_IMPORT_SOURCE = "Imported image"
PDF_IMPORT_SOURCE = "Imported PDF"
DATABASE_IMPORT_SOURCE = "Imported database"
LEGACY_IMPORT_SOURCE = "Imported (scan/image)"

_lock = threading.Lock()
_bank_cache: Optional[List[Dict[str, Any]]] = None


def _load_bank() -> List[Dict[str, Any]]:
    global _bank_cache
    if _bank_cache is None:
        with _lock:
            if _bank_cache is None:
                path = bundled_mcq_bank()
                if not path.exists():
                    _bank_cache = []
                else:
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        _bank_cache = data if isinstance(data, list) else data.get("questions", [])
                    except (json.JSONDecodeError, OSError):
                        _bank_cache = []
    return _bank_cache


def _subject_of(q: Dict[str, Any]) -> str:
    """Subject of a question, tolerating the legacy ``category`` field."""
    return str(q.get("subject") or q.get("category") or "General")


def bundled_questions() -> List[Dict[str, Any]]:
    """Just the read-only questions shipped inside the app bundle."""
    return list(_load_bank())


def _stored_questions_for_bank(include_pdf: bool = False) -> List[Dict[str, Any]]:
    """Writable questions eligible for a quiz source.

    Full question bank includes every writable source except PDF-import-only
    questions. PDF imports stay separate because they are batch-tagged by
    subject and have a dedicated quiz source.
    """
    try:
        from . import question_store
        questions = question_store.all_questions()
    except Exception:
        return []
    if include_pdf:
        return [q for q in questions if q.get("source") == PDF_IMPORT_SOURCE]
    return [q for q in questions if q.get("source") != PDF_IMPORT_SOURCE]


def _all_questions() -> List[Dict[str, Any]]:
    """Bundled bank merged with the user's writable question store.

    The writable store grows from AI-generated questions saved during live
    quizzes. Imported lazily to avoid a circular import (question_store dedups
    against this module).
    """
    return list(_load_bank()) + _stored_questions_for_bank(include_pdf=False)


def list_categories() -> List[str]:
    """Distinct subjects present in the bank (legacy name kept for callers)."""
    cats = {_subject_of(q) for q in _all_questions()}
    return sorted(cats)


def list_topics(subject: Optional[str] = None) -> List[str]:
    """Distinct subtopics in the bank, optionally scoped to one subject."""
    topics = {
        str(q.get("topic"))
        for q in _all_questions()
        if q.get("topic") and (not subject or subject == "All" or _subject_of(q) == subject)
    }
    return sorted(topics)


def count(
    subject: Optional[str] = None,
    difficulty: Optional[str] = None,
    topics: Optional[List[str]] = None,
    source: str = "bank",
) -> int:
    pool = _pdf_questions() if source == "pdf" else _all_questions()
    return len(_filter(pool, subject, difficulty, topics))


def _pdf_questions() -> List[Dict[str, Any]]:
    return _stored_questions_for_bank(include_pdf=True)


def _filter(
    bank: List[Dict[str, Any]],
    subject: Optional[str],
    difficulty: Optional[str],
    topics: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    out = bank
    if subject and subject != "All":
        out = [q for q in out if _subject_of(q) == subject]
    if topics:
        wanted = set(topics)
        out = [q for q in out if q.get("topic") in wanted]
    if difficulty and difficulty != "All":
        out = [q for q in out if q.get("difficulty") == difficulty]
    return out


def sample_questions(
    num_questions: int,
    subject: Optional[str] = None,
    difficulty: Optional[str] = None,
    topics: Optional[List[str]] = None,
    seed: Optional[int] = None,
    source: str = "bank",
) -> List[Dict[str, Any]]:
    """Randomly sample up to ``num_questions`` matching MCQs from the bank.

    ``topics`` (when given) restricts to those subtopics within ``subject``;
    an empty/``None`` list means "all topics in the subject".
    """
    pool = _pdf_questions() if source == "pdf" else _all_questions()
    pool = _filter(pool, subject, difficulty, topics)
    rng = random.Random(seed)
    rng.shuffle(pool)
    return pool[: max(0, num_questions)]
