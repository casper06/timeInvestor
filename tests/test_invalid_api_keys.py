"""A rejected API key says it was rejected — and never shows the key.

Three different FRED failures, three different messages: key not configured,
key rejected by FRED, FRED unreachable. FRED puts the key in the URL, so every
message and log line built from its answers or exceptions is checked for the key.
Same for Gemini's HTTP 400 API_KEY_INVALID. No network: FRED and Gemini are faked
with the answers recorded from the live APIs on 2026-09-30.
"""
import asyncio
import logging
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.config import settings
from backend.main import app
from backend.services import data_fetcher
from backend.services.data_fetcher import (
    FREDDataFetcher,
    FredKeyRejectedError,
    FredSeriesNotFoundError,
)
from backend.services.llm_router import (
    GeminiLLMClient,
    classify_fallback_category,
    _format_fallback_reason,
)
from backend.services.redaction import redact_secrets

client = TestClient(app)

KEY = "0123456789abcdef0123456789abcdef"
GEMINI_KEY = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE12"
NOT_REGISTERED = {
    "error_code": 400,
    "error_message": "Bad Request.  The value for variable api_key is not registered.  "
                     "Read https://fred.stlouisfed.org/docs/api/api_key.html for more information.",
}
MALFORMED = {
    "error_code": 400,
    "error_message": "Bad Request.  The value for variable api_key is not a 32 character "
                     "alpha-numeric lower-case string.  Read https://fred.stlouisfed.org/docs/api/api_key.html "
                     "for more information.",
}
MISSING_SERIES = {"error_code": 400, "error_message": "Bad Request.  The series does not exist."}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    data_fetcher.cache.clear()
    monkeypatch.setattr(settings, "FRED_API_KEY", KEY)
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", False)
    monkeypatch.setattr(routes.fred_fetcher, "api_key", KEY)
    yield
    data_fetcher.cache.clear()


def _fake_fred(monkeypatch, status=None, payload=None, raises=None):
    class FakeResponse:
        status_code = status
        text = str(payload)

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None):
            if raises is not None:
                raise raises
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)


# ---------------------------------------------------------------- redaction

def test_redact_secrets_covers_url_params_known_keys_and_shapes():
    url = f"https://api.stlouisfed.org/fred/series?series_id=UNRATE&api_key={KEY}&file_type=json"
    assert KEY not in redact_secrets(f"ConnectError: {url}")
    assert "api_key=***" in redact_secrets(url)
    assert "series_id=UNRATE" in redact_secrets(url)          # the rest survives
    assert KEY not in redact_secrets(f"clave {KEY} rota", KEY)
    assert GEMINI_KEY not in redact_secrets(f"key {GEMINI_KEY} failed")
    assert redact_secrets("sin nada que ocultar", None, "") == "sin nada que ocultar"


# ---------------------------------------------------------------- FRED: the three causes

@pytest.mark.parametrize("payload", [NOT_REGISTERED, MALFORMED])
def test_rejected_key_is_its_own_error_with_fred_message_and_no_key(monkeypatch, payload):
    _fake_fred(monkeypatch, 400, payload)
    with pytest.raises(FredKeyRejectedError) as e:
        FREDDataFetcher().get_series("UNRATE")
    msg = str(e.value)
    assert "FRED rechazó la clave" in msg and "HTTP 400" in msg
    assert payload["error_message"].split("Read ")[0].strip() in msg   # FRED's own words
    assert "no configurada" not in msg
    assert KEY not in msg
    assert e.value.status_code == 400


def test_rejected_key_is_not_cached(monkeypatch):
    _fake_fred(monkeypatch, 400, NOT_REGISTERED)
    with pytest.raises(FredKeyRejectedError):
        FREDDataFetcher().get_series("UNRATE")
    assert data_fetcher.cache.get("fred_UNRATE_500") is None


def test_key_not_configured_is_not_reported_as_rejected(monkeypatch):
    monkeypatch.setattr(settings, "FRED_API_KEY", None)
    _fake_fred(monkeypatch, 400, NOT_REGISTERED)           # must not even be asked
    with pytest.raises(ValueError) as e:
        FREDDataFetcher().get_series("UNRATE")
    assert not isinstance(e.value, FredKeyRejectedError)
    assert "FRED_API_KEY no configurada" in str(e.value)
    assert "rechaz" not in str(e.value)


def test_fred_down_is_neither_rejected_nor_not_configured(monkeypatch):
    _fake_fred(monkeypatch, 503, {"error_message": "Service Unavailable"})
    with pytest.raises(ValueError) as e:
        FREDDataFetcher().get_series("UNRATE")
    assert not isinstance(e.value, FredKeyRejectedError)
    assert "HTTP 503" in str(e.value)
    assert "no configurada" not in str(e.value) and "rechaz" not in str(e.value)


def test_unknown_series_400_is_still_not_found_not_rejected(monkeypatch):
    _fake_fred(monkeypatch, 400, MISSING_SERIES)
    with pytest.raises(FredSeriesNotFoundError):
        FREDDataFetcher().get_series("NOEXISTE")


def test_metadata_rejected_key(monkeypatch):
    _fake_fred(monkeypatch, 400, NOT_REGISTERED)
    with pytest.raises(FredKeyRejectedError) as e:
        FREDDataFetcher().get_series_metadata("UNRATE")
    assert KEY not in str(e.value)


def test_rejected_key_with_synthetic_allowed_falls_back_saying_why(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)
    _fake_fred(monkeypatch, 400, NOT_REGISTERED)
    series = FREDDataFetcher().get_series("UNRATE")
    assert series.source != "live"
    assert "FRED rechazó la clave" in series.source_detail
    assert KEY not in series.source_detail


# ---------------------------------------------------------------- the key never shows up

def test_key_in_a_network_exception_reaches_neither_logs_nor_messages(monkeypatch, caplog):
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id=UNRATE&api_key={KEY}&file_type=json"
    boom = httpx.ConnectError(f"[Errno 11001] getaddrinfo failed for {url}")
    _fake_fred(monkeypatch, raises=boom)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ValueError) as e1:
        FREDDataFetcher().get_series("UNRATE")
    with pytest.raises(ValueError) as e2:
        FREDDataFetcher().get_series_metadata("UNRATE")

    everything = "\n".join([str(e1.value), str(e2.value)] + [r.getMessage() for r in caplog.records])
    assert "getaddrinfo" in everything          # the useful part is kept...
    assert KEY not in everything                # ...the key is not


def test_key_in_a_fred_error_body_reaches_neither_logs_nor_messages(monkeypatch, caplog):
    _fake_fred(monkeypatch, 500, {"error_message": f"boom for api_key={KEY}"})
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValueError) as e:
        FREDDataFetcher().get_series("UNRATE")
    everything = str(e.value) + "\n".join(r.getMessage() for r in caplog.records)
    assert KEY not in everything


def test_rejected_key_never_logged(monkeypatch, caplog):
    _fake_fred(monkeypatch, 400, NOT_REGISTERED)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(FredKeyRejectedError):
        FREDDataFetcher().get_series("UNRATE")
    with pytest.raises(FredKeyRejectedError):
        FREDDataFetcher().get_series_metadata("UNRATE")
    assert KEY not in "\n".join(r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("path", ["/api/data/macro?series_id=UNRATE", "/api/catalog/fred-metadata?series_id=UNRATE"])
def test_routes_answer_401_with_the_rejection_and_no_key(monkeypatch, caplog, path):
    _fake_fred(monkeypatch, 400, NOT_REGISTERED)
    caplog.set_level(logging.DEBUG)
    resp = client.get(path)
    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert "FRED rechazó la clave" in detail
    assert KEY not in resp.text
    assert KEY not in "\n".join(r.getMessage() for r in caplog.records)


def test_search_concept_logs_no_key(monkeypatch, caplog):
    from backend.services import fred_grounding

    url = f"https://api.stlouisfed.org/fred/series/search?api_key={KEY}"
    _fake_fred(monkeypatch, raises=httpx.ConnectError(f"failed {url}"))
    caplog.set_level(logging.DEBUG)
    assert fred_grounding.search_fred_concept("new home sales", api_key=KEY) == []
    assert KEY not in "\n".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- Gemini

class _GoogleAPIError(Exception):
    """Same shape as google-genai's APIError: `.code` and a message with the body."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


GEMINI_INVALID = (
    "400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid. Please pass a "
    "valid API key.', 'status': 'INVALID_ARGUMENT', 'details': [{'reason': 'API_KEY_INVALID'}]}}"
)


def test_gemini_invalid_key_is_its_own_category():
    assert classify_fallback_category(_GoogleAPIError(400, GEMINI_INVALID)) == "key_rejected"


def test_other_gemini_errors_keep_their_categories():
    assert classify_fallback_category(_GoogleAPIError(401, "UNAUTHENTICATED. API key not valid.")) == "auth_or_config"
    assert classify_fallback_category(_GoogleAPIError(403, "PERMISSION_DENIED")) == "auth_or_config"
    assert classify_fallback_category(_GoogleAPIError(429, "RESOURCE_EXHAUSTED")) == "rate_limit"
    assert classify_fallback_category(_GoogleAPIError(503, "UNAVAILABLE")) == "transient"
    # A 400 that is not about the key (a malformed request) is not "key rejected".
    assert classify_fallback_category(_GoogleAPIError(400, "400 INVALID_ARGUMENT. bad schema")) == "unknown"


def test_gemini_invalid_key_reason_is_readable_and_has_no_raw_blob():
    reason = _format_fallback_reason("Gemini", _GoogleAPIError(400, GEMINI_INVALID))
    assert reason == "Gemini rechazó la clave: API key not valid (API_KEY_INVALID)."
    assert "{" not in reason


def test_gemini_invalid_key_end_to_end_without_network(monkeypatch, caplog):
    import asyncio as _asyncio

    async def no_sleep(*a, **k):
        return None

    monkeypatch.setattr(_asyncio, "sleep", no_sleep)

    def rejected(*args, **kwargs):
        # The key can be echoed back in the SDK's message; it must not survive.
        raise _GoogleAPIError(400, GEMINI_INVALID + f" (key={GEMINI_KEY})")

    def fake_init(self, api_key=None):
        self.api_key = api_key or GEMINI_KEY
        self._client = MagicMock()
        self._client.models.generate_content.side_effect = rejected

    monkeypatch.setattr(GeminiLLMClient, "__init__", fake_init)
    caplog.set_level(logging.DEBUG)

    resp = asyncio.run(GeminiLLMClient().parse_thesis("Demanda de energía por IA"))

    assert resp.provider_used == "mock-semantic-engine"
    assert resp.fallback_category == "key_rejected"
    assert "rechazó la clave" in resp.fallback_reason
    assert GEMINI_KEY not in resp.fallback_reason
    assert GEMINI_KEY not in "\n".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- httpx's own log

def test_httpx_request_log_with_the_key_in_the_url_is_redacted(caplog):
    """httpx logs "HTTP Request: GET <url>" at INFO for every request, and FRED's
    url carries the key (found by running the real server with an invalid key —
    a faked httpx never writes that line)."""
    from backend.services.redaction import install_log_redaction

    install_log_redaction()
    caplog.set_level(logging.INFO)
    url = f"https://api.stlouisfed.org/fred/series?series_id=UNRATE&api_key={KEY}&file_type=json"
    logging.getLogger("httpx").info('HTTP Request: %s %s "HTTP/1.1 200 OK"', "GET", url)

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "HTTP Request: GET" in text and "series_id=UNRATE" in text
    assert KEY not in text
    assert "api_key=***" in text


def test_the_app_installs_log_redaction_on_startup():
    import backend.main  # noqa: F401
    from backend.services.redaction import RedactingFilter

    assert any(isinstance(f, RedactingFilter) for f in logging.getLogger("httpx").filters)
