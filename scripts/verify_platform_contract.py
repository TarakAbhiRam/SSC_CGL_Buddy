"""Verify cross-platform contract and Android build policy.

Run with:
    python scripts/verify_platform_contract.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.api_routes import Api  # noqa: E402
from backend.http_server import app  # noqa: E402

REQUIRED_METHODS = {
    "get_settings",
    "save_settings",
    "test_api_key",
    "delete_api_key",
    "get_syllabus",
    "list_categories",
    "list_topics",
    "bank_count",
    "start_quiz",
    "submit_quiz",
    "save_ai_questions",
    "list_sessions",
    "clear_sessions",
    "import_questions",
    "pick_database_import_file",
    "import_database",
    "export_database",
    "pick_import_file",
    "db_overview",
    "list_db_questions",
    "delete_db_source",
    "delete_db_question",
    "pick_pdf",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def verify_api_methods() -> None:
    missing = sorted(name for name in REQUIRED_METHODS if not callable(getattr(Api, name, None)))
    if missing:
        fail(f"Api is missing methods: {', '.join(missing)}")


def verify_http_routes() -> None:
    routes = {route.path.rsplit("/", 1)[-1] for route in app.routes if route.path.startswith("/api/")}
    missing = sorted(REQUIRED_METHODS - routes)
    if missing:
        fail(f"HTTP API is missing routes: {', '.join(missing)}")


def verify_android_policy() -> None:
    props = (ROOT / "android" / "gradle.properties").read_text(encoding="utf-8")
    for expected in ("cglBuddyMinSdk=28", "cglBuddyTargetSdk=36", "cglBuddyCompileSdk=36"):
        if expected not in props:
            fail(f"Android SDK policy missing {expected}")

    required_files = [
        ROOT / "android" / "settings.gradle",
        ROOT / "android" / "build.gradle",
        ROOT / "android" / "app" / "build.gradle",
        ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml",
        ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "cglbuddy" / "app" / "MainActivity.kt",
        ROOT / "android" / "app" / "src" / "main" / "python" / "android_entry.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_files if not path.exists()]
    if missing:
        fail(f"Android files missing: {', '.join(missing)}")


def main() -> None:
    verify_api_methods()
    verify_http_routes()
    verify_android_policy()
    print("OK: platform contract, HTTP routes, and Android SDK policy are aligned.")


if __name__ == "__main__":
    main()
