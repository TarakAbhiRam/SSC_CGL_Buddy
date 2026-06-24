from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

_server_thread = None


def start_server(files_dir: str) -> None:
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        return

    root = Path(files_dir)
    bundle_root = root / "bundle"
    user_data = root / "user_data"
    bundle_root.mkdir(parents=True, exist_ok=True)
    user_data.mkdir(parents=True, exist_ok=True)

    os.environ["CGL_BUDDY_BUNDLE_ROOT"] = str(bundle_root)
    os.environ["CGL_BUDDY_USER_DATA_DIR"] = str(user_data)

    def run() -> None:
        import uvicorn
        uvicorn.run("backend.http_server:app", host="127.0.0.1", port=8000, log_level="warning")

    _server_thread = threading.Thread(target=run, daemon=True)
    _server_thread.start()
