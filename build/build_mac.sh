#!/usr/bin/env bash
# Build the lightweight macOS .app.
set -euo pipefail

cd "$(dirname "$0")/.."

pyinstaller --noconfirm --windowed --onedir \
  --name "CGL Buddy" \
  --add-data "frontend:frontend" \
  --add-data "data:data" \
  --collect-data webview \
  main.py

echo "Built dist/CGL Buddy.app — open it with: open 'dist/CGL Buddy.app'"
