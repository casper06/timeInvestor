"""
fix/fred-metadata: a FRED series carries FRED's own title, units, frequency and
seasonal adjustment (/fred/series). When FRED's metadata can't be had, nothing
is made up: no "FRED Series X", no "Index" by default, no hand-written catalog
name. Fake FRED; no network.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.services.data_fetcher import FREDDataFetcher, cache

OBS = {"observations": [{"date": f"2025-{m:02d}-01", "value": str(100 + m)} for m in range(1, 13)]}
META = {"seriess": [{"id": "X", "title": "Producer Price Index by Industry: Electric Power Generation",
                     "units": "Index Dec 2003=100", "frequency": "Monthly",
                     "seasonal_adjustment": "Not Seasonally Adjusted", "seasonal_adjustment_short": "NSA",
                     "notes": "n"}]}


def _fake_fred(monkeypatch, meta_status=200):
    class Resp:
        def __init__(self, status, payload):
            self.status_code, self._p, self.text = status, payload, str(payload)

        def json(self):
            return self._p

    class Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            if url.endswith("/observations"):
                return Resp(200, OBS)
            return Resp(meta_status, META if meta_status == 200 else {"error_message": "Internal Server Error"})

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr(settings, "FRED_API_KEY", "fake-test-key")
    cache.clear()


def test_series_carries_freds_own_metadata(monkeypatch):
    _fake_fred(monkeypatch)
    s = FREDDataFetcher().get_series("PCU221110221110")
    assert s.name == "Producer Price Index by Industry: Electric Power Generation"
    assert s.unit == "Index Dec 2003=100"
    assert (s.source_frequency, s.seasonal_adjustment, s.seasonal_adjustment_short) == (
        "Monthly", "Not Seasonally Adjusted", "NSA")
    assert s.metadata_source == "fred"


def test_a_catalog_series_gets_freds_title_not_the_hand_written_one(monkeypatch):
    _fake_fred(monkeypatch)
    assert "IPG2211A2N" in FREDDataFetcher.SERIES_CATALOG
    s = FREDDataFetcher().get_series("IPG2211A2N")
    assert s.name == META["seriess"][0]["title"]
    assert s.name != FREDDataFetcher.SERIES_CATALOG["IPG2211A2N"]["name"]


def test_without_freds_metadata_nothing_is_made_up(monkeypatch):
    _fake_fred(monkeypatch, meta_status=500)
    s = FREDDataFetcher().get_series("PCU221110221110")
    assert len(s.points) == 12                                   # the data itself did arrive
    assert s.name == "PCU221110221110" and "FRED Series" not in s.name
    assert s.unit is None                                        # not "Index"
    assert s.metadata_source == "unavailable" and "metadatos no disponibles" in s.metadata_note


def test_a_cache_hit_keeps_the_metadata(monkeypatch):
    _fake_fred(monkeypatch)
    FREDDataFetcher().get_series("PCU221110221110")
    again = FREDDataFetcher().get_series("PCU221110221110")
    assert again.from_cache and again.unit == "Index Dec 2003=100" and again.seasonal_adjustment_short == "NSA"


def test_the_macro_route_returns_the_metadata(monkeypatch):
    _fake_fred(monkeypatch)
    body = TestClient(app).get("/api/data/macro", params={"series_id": "PCU221110221110"}).json()
    assert body["unit"] == "Index Dec 2003=100" and body["seasonal_adjustment_short"] == "NSA"
    assert body["source_frequency"] == "Monthly" and body["metadata_source"] == "fred"


def test_synthetic_reference_series_has_no_invented_unit(monkeypatch):
    monkeypatch.setattr(settings, "FRED_API_KEY", "")
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)
    cache.clear()
    s = FREDDataFetcher().get_series("IPG2211A2N")
    assert s.source == "synthetic" and s.unit is None and s.metadata_source == "unavailable"


@pytest.mark.parametrize("unit", [None, "Percent"])
def test_backtest_verdict_never_prints_a_missing_unit(monkeypatch, unit):
    from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
    from backend.services.backtest_engine import BacktestEngine
    from backend.services.forecast_engine import DampedHoltForecastEngine
    pts = [TimeSeriesPoint(timestamp=f"{2000 + i // 12}-{i % 12 + 1:02d}-01", value=100 + i * 0.3 + (i % 5)) for i in range(120)]
    data = TimeSeriesData(id="X", name="X", type="macro", unit=unit, points=pts, source="live")
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, *a, **k: data)
    res = BacktestEngine.run_backtest(series_id="X", cutoff_date=pts[100].timestamp, horizon=12, is_macro=True,
                                      engine_override=DampedHoltForecastEngine())
    assert "None" not in res.verdict
    assert (unit or "") in res.verdict
