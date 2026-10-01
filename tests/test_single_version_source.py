"""The app's version is written once, in the VERSION file.

If someone types it by hand somewhere else (a second `version="1.0.1"` in the
FastAPI app, a "v2.0" badge in the UI, a Dockerfile label...), the two drift
apart and nobody notices until a release says one thing and the app another.
"""
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.version import VERSION_FILE, __version__

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "__pycache__", ".pytest_cache",
             "docs", ".bitacora", "tests", "data"}
SCANNED = {".py", ".ts", ".tsx", ".js", ".json", ".yml", ".yaml", ".toml", ".cfg"}
# Where a version number legitimately appears: the source of truth, the history,
# and the npm lockfile of the frontend (its package version is a placeholder).
ALLOWED = {"VERSION", "CHANGELOG.md", "package.json", "package-lock.json", "version.py"}
HAND_WRITTEN = re.compile(r"""(?ix) (?:__version__|\bversion) ["']? \s* [=:] \s* ["'] \d+\.\d+\.\d+ """)


def _sources():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if name in ALLOWED:
                continue
            if path.suffix in SCANNED or name.startswith("Dockerfile"):
                yield path


def test_version_file_is_a_plain_semver():
    assert VERSION_FILE == ROOT / "VERSION"
    assert SEMVER.match(__version__), f"VERSION must be MAJOR.MINOR.PATCH, got {__version__!r}"


def test_the_app_and_health_report_the_version_file():
    assert app.version == __version__
    health = TestClient(app).get("/api/health").json()
    assert health["version"] == __version__


def test_nobody_writes_the_version_by_hand_elsewhere():
    offenders = []
    for path in _sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if HAND_WRITTEN.search(line) or re.search(rf"(?<![\d.]){re.escape(__version__)}(?![\d.])", line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:100]}")
    assert not offenders, (
        "The version lives only in VERSION (read by backend/version.py). Found it written by hand:\n  "
        + "\n  ".join(offenders)
    )


def test_the_frontend_package_does_not_declare_its_own_version():
    """package.json's "version" is npm's placeholder; the app version comes from
    /api/health. Keep it at the placeholder so it can't pose as a second source."""
    import json

    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == "0.0.0"


def test_docker_images_ship_the_version_file():
    """backend/version.py reads it at import time: an image without it won't start."""
    for name in ("Dockerfile", "Dockerfile.timesfm"):
        assert re.search(r"^COPY .*\bVERSION\b", (ROOT / name).read_text(encoding="utf-8"), re.M), name
