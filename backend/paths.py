"""Centralised, cross-platform path resolution.

Works both in normal `python main.py` runs and inside a PyInstaller-frozen
bundle (where data files live under the temporary ``sys._MEIPASS`` dir).

Read-only bundled assets (frontend, mcq bank) are
resolved relative to the bundle. Writable state (config.json, the user-upload
question bank, sessions) is stored in a per-user app-data directory so it
survives even when the app itself lives in a read-only location.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Root for read-only bundled resources.

    - Frozen (PyInstaller): the extraction dir ``sys._MEIPASS``.
    - Source run: the project root (parent of this ``backend`` package).
    """
    android_bundle = os.environ.get("CGL_BUDDY_BUNDLE_ROOT")
    if android_bundle:
        return Path(android_bundle)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled, read-only resource."""
    return _bundle_root().joinpath(*parts)


def user_data_dir() -> Path:
    """Per-user writable directory for app state (config, uploads).

    Uses platform conventions:
    - Windows: %APPDATA%\CGL_Buddy
    - macOS:   ~/Library/Application Support/CGL_Buddy
    - Linux:   $XDG_CONFIG_HOME/CGL_Buddy or ~/.config/CGL_Buddy

    Existing installs used ``SSC_MCQ``. If the new directory is empty and the
    old one exists, copy user files forward so settings/questions survive the
    rename.
    """
    app_name = "CGL_Buddy"
    old_app_name = "SSC_MCQ"
    android_data = os.environ.get("CGL_BUDDY_USER_DATA_DIR")
    if android_data:
        path = Path(android_data)
        path.mkdir(parents=True, exist_ok=True)
        return path
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / app_name
    old_path = Path(base) / old_app_name
    path.mkdir(parents=True, exist_ok=True)
    if old_path.exists() and not any(path.iterdir()):
        import shutil

        for child in old_path.iterdir():
            target = path / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True)
            elif child.is_file() and not target.exists():
                shutil.copy2(child, target)
    return path


# --- Common resource locations ---------------------------------------------

def frontend_dir() -> Path:
    return resource_path("frontend")


def bundled_chroma_dir() -> Path:
    """Prebuilt (read-only) vector index shipped with the app."""
    return resource_path("data", "chroma_db")


def bundled_mcq_bank() -> Path:
    """Prebuilt MCQ pool shipped with the app."""
    return resource_path("data", "mcq_bank.json")


def pdfs_dir() -> Path:
    """Source PDFs (dev/offline-prep only)."""
    return resource_path("data", "pdfs")


def config_path() -> Path:
    """Writable config file in the per-user data dir."""
    return user_data_dir() / "config.json"


def sessions_path() -> Path:
    """Writable file storing the user's past quiz sessions."""
    return user_data_dir() / "sessions.json"


def user_chroma_dir() -> Path:
    """Writable chroma collection for user-uploaded PDFs."""
    path = user_data_dir() / "chroma_db_user"
    path.mkdir(parents=True, exist_ok=True)
    return path
