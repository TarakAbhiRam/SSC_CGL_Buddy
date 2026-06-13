"""Read/write the local config file (API keys + last-used settings).

Stored in the per-user app-data dir (see :mod:`backend.paths`), NOT in the
bundle, so it is writable and survives app updates. Never committed to git.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict

from .paths import config_path

_LOCK = threading.Lock()

DEFAULT_CONFIG: Dict[str, Any] = {
    "gemini_key": "",
    "groq_key": "",
    "active_provider": "groq",
    "auto_save_ai": False,   # auto-persist AI-generated questions to the bank
    "last_settings": {
        "mode": "bank",          # bank | live | pdf
        "category": "All",
        "difficulty": "All",     # All | easy | medium | hard
        "topics": [],            # selected subtopics within the subject
        "num_questions": 10,
        "duration_minutes": 15,
    },
}


def load_config() -> Dict[str, Any]:
    """Load config, merging on top of defaults. Never raises on missing/corrupt file."""
    path = config_path()
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    merged = {**DEFAULT_CONFIG, **data}
    # Deep-merge the nested settings dict so new defaults appear for old configs.
    merged["last_settings"] = {
        **DEFAULT_CONFIG["last_settings"],
        **(data.get("last_settings") or {}),
    }
    return merged


def save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Persist config atomically. Returns the saved config."""
    path = config_path()
    with _LOCK:
        current = load_config()
        current.update({k: v for k, v in config.items() if k != "last_settings"})
        if "last_settings" in config and config["last_settings"]:
            current["last_settings"] = {
                **current.get("last_settings", {}),
                **config["last_settings"],
            }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.replace(path)
    return current


def get_api_key(provider: str) -> str:
    cfg = load_config()
    return (cfg.get(f"{provider}_key") or "").strip()


def clear_key(provider: str) -> Dict[str, Any]:
    """Remove the stored API key for a provider. Returns the saved config."""
    field = f"{provider}_key"
    path = config_path()
    with _LOCK:
        current = load_config()
        current[field] = ""
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.replace(path)
    return current
