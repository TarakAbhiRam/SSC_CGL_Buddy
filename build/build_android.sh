#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../android"

if command -v ./gradlew >/dev/null 2>&1 && [[ -x ./gradlew ]]; then
  ./gradlew :app:assembleDebug
elif command -v gradle >/dev/null 2>&1; then
  gradle :app:assembleDebug
else
  echo "Gradle is required. Install Android Studio or Gradle, then rerun this script." >&2
  exit 1
fi

echo "Built android/app/build/outputs/apk/debug/app-debug.apk"
