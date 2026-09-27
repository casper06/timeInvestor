"""
4.16: a FRED ID that doesn't exist says so — in the fetcher, in both routes
the UI uses, and never with a synthetic stand-in. FRED's real answer for an
unknown ID (checked against the live API on 2026-09-27) is HTTP 400
{"error_code": 400, "error_message": "Bad Request.  The series does not exist."}
on both /fred/series and /fred/series/observations.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.config import settings
from backend.main import app
from backend.services.data_fetcher import FREDDataFetcher, FredSeriesNotFoundError

client = TestClient(app)
MISSING = {"error_code": 400, "error_message": "Bad Request.  The series does not exist."}


def _fake_fred(monkeypatch, status, payload):
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
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(settings, "FRED_API_KEY", "fake-test-key")


def test_get_series_unknown_id_raises_not_found_even_if_synthetic_is_allowed(monkeypatch):
    _fake_fred(monkeypatch, 400, MISSING)
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)
    with pytest.raises(FredSeriesNotFoundError) as e:
        FREDDataFetcher().get_series("NOEXISTE416")
    assert "no existe en FRED" in str(e.value) and "NOEXISTE416" in str(e.value)


def test_other_fred_errors_keep_the_old_path(monkeypatch):
    """A 500 from FRED is not "doesn't exist": same ValueError as before."""
    _fake_fred(monkeypatch, 500, {"error_message": "Internal Server Error"})
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", False)
    with pytest.raises(ValueError) as e:
        FREDDataFetcher().get_series("IPG2211A2N_500")
    assert not isinstance(e.value, FredSeriesNotFoundError)
    assert "ALLOW_SYNTHETIC_DATA=false" in str(e.value)


def test_get_series_metadata_unknown_id_raises_not_found(monkeypatch):
    _fake_fred(monkeypatch, 400, MISSING)
    with pytest.raises(FredSeriesNotFoundError):
        FREDDataFetcher().get_series_metadata("NOEXISTE416META")


@pytest.mark.parametrize("path", ["/api/data/macro", "/api/catalog/fred-metadata"])
def test_routes_answer_404_with_a_code_for_an_unknown_id(monkeypatch, path):
    def missing(series_id, **kwargs):
        raise FredSeriesNotFoundError(series_id)

    monkeypatch.setattr(routes.fred_fetcher, "get_series", missing)
    monkeypatch.setattr(routes.fred_fetcher, "get_series_metadata", missing)
    r = client.get(path, params={"series_id": "NOEXISTE416"})
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "fred_series_not_found"
    assert "La serie 'NOEXISTE416' no existe en FRED" in body["detail"]


def test_no_key_404_has_no_not_found_code(monkeypatch):
    """"Couldn't query FRED" stays a plain 404 (test_api_endpoints), without the
    code: the UI must not call that "doesn't exist"."""
    def no_key(series_id):
        raise ValueError(f"No se pudo obtener metadata de FRED para '{series_id}' (clave FRED_API_KEY no configurada)")

    monkeypatch.setattr(routes.fred_fetcher, "get_series_metadata", no_key)
    r = client.get("/api/catalog/fred-metadata", params={"series_id": "IPG2211A2N"})
    assert r.status_code == 404 and "code" not in r.json()
