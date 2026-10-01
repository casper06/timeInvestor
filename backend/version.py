"""The app's version, read from the VERSION file at the repo root.

That file is the only place the version is written. Everything else (the
FastAPI app, /api/health, the UI header) takes it from here; a test fails if
the number is typed by hand anywhere else.
"""
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
__version__ = VERSION_FILE.read_text(encoding="utf-8").strip()
