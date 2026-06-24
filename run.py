#!/usr/bin/env python
"""CGL Buddy multi-platform launcher.

Allows choosing between:
1. Desktop (PyWebView) - native app experience
2. HTTP server - for Android/web/testing
3. Both - desktop with HTTP server in background

Usage:
  python run.py              # Interactive mode (choose which to run)
  python run.py --desktop    # Desktop only
  python run.py --http       # HTTP server only
  python run.py --both       # Both (desktop + HTTP server)
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("CGL_Buddy.launcher")


def run_desktop():
    """Run the desktop PyWebView app."""
    log.info("Starting desktop app (PyWebView)...")
    from main import main
    main()


def run_http_server():
    """Run the HTTP server."""
    log.info("Starting HTTP server on http://127.0.0.1:8000...")
    
    try:
        import uvicorn
        uvicorn.run(
            "backend.http_server:app",
            host="127.0.0.1",
            port=8000,
            log_level="info",
        )
    except KeyboardInterrupt:
        log.info("HTTP server stopped.")


def run_both():
    """Run both desktop and HTTP server."""
    log.info("Starting both desktop and HTTP server...")
    log.info("HTTP server will start in background; desktop will run in foreground.")
    
    # Start HTTP server in background thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    # Give server time to start
    time.sleep(2)
    
    # Run desktop in main thread
    run_desktop()


def interactive_mode():
    """Interactive mode to choose which to run."""
    print("\nCGL Buddy - Choose startup mode:")
    print("1. Desktop (PyWebView)")
    print("2. HTTP server (for Android/web/testing)")
    print("3. Both (desktop + HTTP server)")
    print("4. Exit")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        run_desktop()
    elif choice == "2":
        run_http_server()
    elif choice == "3":
        run_both()
    elif choice == "4":
        log.info("Exiting.")
        sys.exit(0)
    else:
        print("Invalid choice. Please try again.")
        interactive_mode()


def main():
    parser = argparse.ArgumentParser(
        description="CGL Buddy multi-platform launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py              # Interactive mode
  python run.py --desktop    # Desktop only
  python run.py --http       # HTTP server only
  python run.py --both       # Both modes
        """,
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Run desktop (PyWebView) only",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run HTTP server only",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="Run both desktop and HTTP server",
    )
    
    args = parser.parse_args()
    
    if args.desktop:
        run_desktop()
    elif args.http:
        run_http_server()
    elif args.both:
        run_both()
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
