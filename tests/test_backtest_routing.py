"""
/api/backtest routes a FRED series outside FREDDataFetcher.SERIES_CATALOG to
FRED when the request says it's macro (item 2.7). Synthetic monthly series,
generated only for these tests; the fetchers are replaced so nothing goes to
the network.
"""
import numpy as np
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.data_fetcher import FREDDataFetcher, MarketDataFetcher

client = TestClient(app)


def _monthly(sid="UNRATE", n=240):
    rng = np.random.default_rng(5)
    vals = 5 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    pts = [TimeSeriesPoint(timestamp=f"{2005 + i // 12:04d}-{i % 12 + 1:02d}-01", value=float(v)) for i, v in enumerate(vals)]
    return TimeSeriesData(id=sid, name=sid, type="macro", unit="%", points=pts, source="live")


def _spy_fetchers(monkeypatch, fred_series=None):
    calls = {"fred": 0, "market": 0}

    def fred(self, sid, *a, **k):
        calls["fred"] += 1
        return fred_series or _monthly(sid)

    def market(ticker, *a, **k):
        calls["market"] += 1
        raise ValueError(f"No se pudieron obtener datos de mercado para '{ticker}' "
                         f"(yfinance devolvió dataframe vacío para {ticker}) y ALLOW_SYNTHETIC_DATA=false")

    monkeypatch.setattr(FREDDataFetcher, "get_series", fred)
    monkeypatch.setattr(MarketDataFetcher, "get_history", staticmethod(market))
    return calls


def test_macro_series_outside_the_catalog_goes_to_fred(monkeypatch):
    assert "UNRATE" not in FREDDataFetcher.SERIES_CATALOG
    calls = _spy_fetchers(monkeypatch)
    resp = client.post("/api/backtest", json={
        "series_id": "UNRATE", "cutoff_date": "2020-12-01", "horizon": 12, "series_type": "macro"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert calls == {"fred": 1, "market": 0}
    assert body["frequency"] == "monthly" and body["metrics"]["observations_evaluated"] == 12
    assert body["future_actual_dates"][0] == "2021-01-01"


def test_without_series_type_the_error_says_what_to_send(monkeypatch):
    calls = _spy_fetchers(monkeypatch)
    resp = client.post("/api/backtest", json={"series_id": "UNRATE", "cutoff_date": "2020-12-01", "horizon": 12})
    assert resp.status_code == 400
    assert calls["market"] == 1 and calls["fred"] == 0  # unchanged behavior without the type
    assert "series_type='macro'" in resp.json()["detail"]


def test_equity_type_keeps_going_to_yfinance(monkeypatch):
    calls = _spy_fetchers(monkeypatch)
    resp = client.post("/api/backtest", json={
        "series_id": "NVDA", "cutoff_date": "2020-12-01", "horizon": 12, "series_type": "equity"})
    assert resp.status_code == 400 and calls == {"fred": 0, "market": 1}
    assert "series_type='macro'" not in resp.json()["detail"]  # the type was given: no hint


def test_catalog_series_still_go_to_fred_without_the_type(monkeypatch):
    calls = _spy_fetchers(monkeypatch, fred_series=_monthly("INDPRO"))
    resp = client.post("/api/backtest", json={"series_id": "INDPRO", "cutoff_date": "2020-12-01", "horizon": 12})
    assert resp.status_code == 200 and calls == {"fred": 1, "market": 0}


def test_unknown_series_type_is_rejected():
    resp = client.post("/api/backtest", json={
        "series_id": "UNRATE", "cutoff_date": "2020-12-01", "horizon": 12, "series_type": "fred"})
    assert resp.status_code == 422
