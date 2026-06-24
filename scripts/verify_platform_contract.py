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


def verify_mobile_android_policy() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-android.yml").read_text(encoding="utf-8")
    for expected in (
        "actions/setup-node@v4",
        'node-version: "22.13.0"',
        'java-version: "21"',
        "cache-dependency-path: mobile/package-lock.json",
        "working-directory: mobile",
        "working-directory: mobile/android",
        "./gradlew assembleDebug --warning-mode all",
    ):
        if expected not in workflow:
            fail(f"Mobile Android workflow missing {expected}")

    variables = (ROOT / "mobile" / "android" / "variables.gradle").read_text(encoding="utf-8")
    for expected in ("minSdkVersion = 28", "targetSdkVersion = 36", "compileSdkVersion = 36"):
        if expected not in variables:
            fail(f"Mobile Android SDK policy missing {expected}")

    capacitor_gradle = (ROOT / "mobile" / "android" / "app" / "capacitor.build.gradle").read_text(encoding="utf-8")
    if "JavaVersion.VERSION_21" not in capacitor_gradle:
        fail("Mobile Android Java policy missing JavaVersion.VERSION_21")

    wrapper = (ROOT / "mobile" / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text(encoding="utf-8")
    if "gradle-8.14.3-all.zip" not in wrapper:
        fail("Mobile Android Gradle wrapper policy missing Gradle 8.14.3")

    android_gradle = (ROOT / "mobile" / "android" / "build.gradle").read_text(encoding="utf-8")
    if "com.android.tools.build:gradle:8.13.0" not in android_gradle:
        fail("Mobile Android Gradle plugin policy missing AGP 8.13.0")

    package_json = (ROOT / "mobile" / "package.json").read_text(encoding="utf-8")
    if '"node": ">=22.13.0"' not in package_json:
        fail("Mobile package.json missing Node >=22.13.0 engine policy")

    required_files = [
        ROOT / "mobile" / "package.json",
        ROOT / "mobile" / "package-lock.json",
        ROOT / "mobile" / "capacitor.config.ts",
        ROOT / "mobile" / "android" / "gradlew",
        ROOT / "mobile" / "android" / "app" / "build.gradle",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_files if not path.exists()]
    if missing:
        fail(f"Mobile Android files missing: {', '.join(missing)}")


def main() -> None:
    verify_api_methods()
    verify_http_routes()
    verify_android_policy()
    verify_mobile_android_policy()
    print("OK: platform contract, HTTP routes, and Android SDK policy are aligned.")


if __name__ == "__main__":
    main()
