"""
4.11 (partial): where a series is fetched from. A FRED ID is never looked up
in yfinance — not in the correlation, not in the backtest — whether it's in
the fixed catalog or not (PCU221110221110 isn't). Fakes for FRED and
yfinance; no network.
"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services import series_routing
from backend.services.correlation_engine import CorrelationEngine
from backend.services.data_fetcher import FREDDataFetcher, MarketDataFetcher
from backend.services.series_routing import is_fred_series

client = TestClient(app)
FRED_IDS = {"PCU221110221110", "DGS10", "UNRATE"}


def _series(sid, kind, n=400):
    dates = pd.bdate_range("2024-01-01", periods=n)
    vals = [100 + i * 0.1 + (i % 7) * 0.3 * (1 if kind == "macro" else -1) for i in range(n)]
    return TimeSeriesData(id=sid, name=sid, type=kind, unit="x", source="live",
                          points=[TimeSeriesPoint(timestamp=d.strftime("%Y-%m-%d"), value=v) for d, v in zip(dates, vals)])


@pytest.fixture
def fakes(monkeypatch):
    calls = {"fred": [], "yf": []}

    def fred_get(self, series_id, limit=500):
        calls["fred"].append(series_id)
        return _series(series_id, "macro")

    def yf_get(ticker, period="2y", interval="1d"):
        calls["yf"].append(ticker)
        if ticker in FRED_IDS:
            raise AssertionError(f"{ticker} es de FRED y se buscó en yfinance")
        return _series(ticker, "equity")

    monkeypatch.setattr(FREDDataFetcher, "get_series", fred_get)
    monkeypatch.setattr(MarketDataFetcher, "get_history", staticmethod(yf_get))
    # FRED "knows" its IDs; anything else doesn't exist there.
    monkeypatch.setattr(series_routing, "_fred_knows", lambda sid: sid in FRED_IDS)
    return calls


def test_the_callers_type_decides_without_asking_fred(monkeypatch):
    def boom(sid):
        raise AssertionError("no hace falta preguntarle a FRED")
    monkeypatch.setattr(series_routing, "_fred_knows", boom)
    assert is_fred_series("PCU221110221110", "macro") is True
    assert is_fred_series("NVDA", "equity") is False
    assert is_fred_series("IPG2211A2N") is True          # the catalog, still no FRED call


def test_untyped_ids_are_asked_to_fred(fakes):
    assert is_fred_series("PCU221110221110") is True
    assert is_fred_series("NVDA") is False


def test_fred_unreachable_keeps_the_old_yfinance_path(monkeypatch):
    monkeypatch.setattr(series_routing, "_fred_knows", lambda sid: None)
    assert is_fred_series("PCU221110221110") is False


def test_correlation_untyped_fred_ids_outside_the_catalog_go_to_fred(fakes):
    res = CorrelationEngine.calculate_correlations(["PCU221110221110", "DGS10", "NVDA"], period="2y")
    assert set(res.series_ids) == {"PCU221110221110", "DGS10", "NVDA"}
    assert sorted(fakes["fred"]) == ["DGS10", "PCU221110221110"]
    assert fakes["yf"] == ["NVDA"]


def test_correlation_route_with_types_never_asks_yfinance_for_a_macro_id(fakes, monkeypatch):
    monkeypatch.setattr(series_routing, "_fred_knows", lambda sid: None)   # FRED can't even be asked
    r = client.post("/api/correlation", json={
        "series_ids": ["PCU221110221110", "DGS10"],
        "series_types": {"PCU221110221110": "macro", "DGS10": "macro"},
    })
    assert r.status_code == 200, r.text
    assert fakes["yf"] == [] and sorted(fakes["fred"]) == ["DGS10", "PCU221110221110"]


def test_backtest_route_untyped_fred_id_goes_to_fred(fakes):
    r = client.post("/api/backtest", json={"series_id": "PCU221110221110", "cutoff_date": "2025-01-01", "horizon": 12})
    assert "PCU221110221110" in fakes["fred"] and "PCU221110221110" not in fakes["yf"]
    assert r.status_code in (200, 400, 422)   # the answer itself is not under test here


def test_empty_yfinance_says_allow_synthetic_once(monkeypatch):
    class Empty:
        def __init__(self, sym):
            pass

        def history(self, period=None, interval=None):
            return pd.DataFrame()

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", Empty)
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", False)
    with pytest.raises(ValueError) as e:
        MarketDataFetcher.get_history("NOSUCHTICKER416", period="3mo")
    msg = str(e.value)
    assert msg.count("ALLOW_SYNTHETIC_DATA=false") == 1, msg
    assert "dataframe vacío" in msg
