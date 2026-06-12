"""PyWebView entry point.

Creates the native window, points it at the bundled frontend, and exposes the
:class:`backend.api_routes.Api` bridge to JavaScript. Paths are resolved via
:mod:`backend.paths` so this works both from source and inside a PyInstaller
bundle on Windows or macOS.
"""

from __future__ import annotations

import logging
import os

import webview

from backend.api_routes import Api
from backend.paths import frontend_dir

WINDOW_TITLE = "CGL Buddy"

# Set CGL_BUDDY_DEBUG=1 to open Web Inspector / DevTools (right-click -> Inspect)
# and enable verbose backend logging in the terminal. SSC_MCQ_DEBUG is accepted
# for compatibility with older local scripts.
DEBUG = (
    os.environ.get("CGL_BUDDY_DEBUG", "").strip() in ("1", "true", "True")
    or os.environ.get("SSC_MCQ_DEBUG", "").strip() in ("1", "true", "True")
)


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if DEBUG else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("CGL_Buddy").info("Starting app (debug=%s)", DEBUG)

    api = Api()
    index = frontend_dir() / "index.html"

    webview.create_window(
        WINDOW_TITLE,
        url=str(index),
        js_api=api,
        width=1100,
        height=780,
        min_size=(900, 640),
    )
    # gui=None lets pywebview pick the best backend per-OS
    # (EdgeChromium on Windows, WebKit on macOS).
    webview.start(debug=DEBUG)


if __name__ == "__main__":
    main()
