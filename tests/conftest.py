# The whole suite runs against a throwaway SQLite database, never the
# project's real backend/database/time_investor.db. backend.config reads
# DATABASE_URL when it's first imported (and load_dotenv doesn't override an
# existing variable), so this has to happen before anything from `backend` is
# imported — which is why it sits above the other imports.
import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="timeinvestor-tests-"))
_TEST_DB_PATH = _TEST_DB_DIR / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
# Also on an aborted run, where the session fixture never reaches its cleanup.
atexit.register(shutil.rmtree, _TEST_DB_DIR, True)

import pytest  # noqa: E402

import backend.services.llm_availability as availability  # noqa: E402
from backend.database import connection  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_series_routing(monkeypatch):
    """series_routing asks FRED whether an untyped ID is a FRED series. The
    suite never does that over the network: by default FRED "can't be asked"
    (same as no key). tests/test_series_routing.py replaces it with fakes."""
    from backend.services import series_routing
    series_routing.clear_routing_cache()
    monkeypatch.setattr(series_routing, "_fred_knows", lambda series_id: None)


@pytest.fixture(autouse=True)
def _offline_copilot_evidence(monkeypatch):
    """The copilot's FRED evidence is fetched server side; the suite never
    does that over the network (tests/test_copilot_context.py fakes it)."""
    from backend.services import copilot_context

    def offline(series_id):
        raise ValueError("sin red en los tests")
    monkeypatch.setattr(copilot_context, "_fetch_series", offline)


@pytest.fixture(scope="session", autouse=True)
def _isolated_test_database():
    """Refuses to run if the app's engine isn't the temporary database (e.g.
    something imported backend before this file set DATABASE_URL), then
    creates the tables there. Removed at the end of the session."""
    actual = Path(connection.engine.url.database).resolve()
    if actual != _TEST_DB_PATH.resolve():
        pytest.exit(
            f"La suite no está usando la DB temporal ({_TEST_DB_PATH}) sino {actual}. "
            f"Se aborta para no escribir en una DB real.",
            returncode=3,
        )
    connection.init_db()
    yield
    connection.engine.dispose()
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clear_llm_availability_cache():
    """A Gemini CLI account rejection in one test pins gemini_cli as unavailable
    in the process-wide availability cache; never let that leak across tests."""
    availability.clear_availability_cache()
    yield
    availability.clear_availability_cache()
