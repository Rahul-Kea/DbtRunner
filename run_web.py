#!/usr/bin/env python3
"""Run the dbt DuckLake Web Application and Runner API.

Usage:
    python3 run_web.py [--host 127.0.0.1] [--port 8000] [--dev]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"


def build_frontend_if_needed() -> None:
    if not (FRONTEND_DIST / "index.html").is_file():
        print("Frontend production build not found. Building with npm run build...")
        subprocess.run(["npm", "run", "build"], cwd=FRONTEND_DIR, check=True)
        print("Frontend built successfully.")


def run_dev() -> None:
    """Run both Vite dev server and FastAPI backend in parallel."""
    import uvicorn
    print("\n" + "=" * 60)
    print("Starting dbt Runner in DEV mode:")
    print("  • Vite Frontend Dev: http://localhost:5173")
    print("  • FastAPI API Server: http://127.0.0.1:8000")
    print("=" * 60 + "\n")

    vite_proc = subprocess.Popen(["npm", "run", "dev"], cwd=FRONTEND_DIR)
    try:
        uvicorn.run("server.app:app", host="127.0.0.1", port=8000, reload=True)
    finally:
        vite_proc.terminate()
        vite_proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="dbt DuckLake Sandbox Web Runner")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--dev", action="store_true", help="Run with Vite dev server (HMR)")
    parser.add_argument("--open", action="store_true", help="Open browser on start")
    args = parser.parse_args()

    if args.dev:
        run_dev()
        return

    build_frontend_if_needed()

    import uvicorn

    url = f"http://{args.host}:{args.port}"
    print("\n" + "=" * 65)
    print("🚀 dbt DuckLake & DuckDB Web Runner is running!")
    print(f"👉 Web Application UI:  {url}")
    print(f"👉 API Documentation:   {url}/docs")
    print("=" * 65 + "\n")

    if args.open:
        webbrowser.open(url)

    uvicorn.run("server.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
