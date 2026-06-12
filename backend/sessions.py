"""Persistent store for completed quiz sessions.

Each session records when it was taken, how long it took, the configuration
used (subject/topics/mode/difficulty) and the resulting stats (score,
accuracy, per-difficulty and per-category breakdowns). Stored as a JSON list
in the per-user app-data dir so history survives app restarts/updates.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from .paths import sessions_path

_LOCK = threading.Lock()

# Cap history so the file never grows unbounded; newest are kept.
MAX_SESSIONS = 200


def _read() -> List[Dict[str, Any]]:
    path = sessions_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write(sessions: List[Dict[str, Any]]) -> None:
    path = sessions_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def list_sessions() -> List[Dict[str, Any]]:
    """All saved sessions, newest first."""
    sessions = _read()
    sessions.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
    return sessions


def save_session(record: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a completed session and return the stored record.

    ``record`` should carry the quiz config and scored stats; this function
    stamps an id and timestamp and trims the history to ``MAX_SESSIONS``.
    """
    entry = dict(record)
    entry.setdefault("id", uuid.uuid4().hex[:12])
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with _LOCK:
        sessions = _read()
        sessions.append(entry)
        # Keep only the most recent MAX_SESSIONS by timestamp.
        sessions.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        sessions = sessions[:MAX_SESSIONS]
        _write(sessions)
    return entry


def clear_sessions() -> None:
    """Delete all saved sessions."""
    with _LOCK:
        _write([])
