"""
Unit tests for data provenance preservation through cache (Fix: Cache Provenance).
Ensures that:
1. Live data served from cache retains source='live' and has from_cache=True (no false positives).
2. Synthetic data served from cache retains source='synthetic' and is rejected by all quantitative engines (no false negatives).
3. FRED and Fundamentals fetchers preserve provenance when serving from cache.
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings
from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher, cache

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_cache_before_and_after():
    cache.clear()
    yield
    cache.clear()


# pandas 3.0.1 returns 99 dates, not 100, for date_range(end=<weekend>,
# periods=100, freq="B"); a fixed 100-value column then fails on weekends.
# Saturday and Sunday are pinned so that stays covered on any weekday.
@pytest.mark.parametrize("end", [None, "2026-09-26 15:00", "2026-09-27 15:00"], ids=["now", "saturday", "sunday"])
def test_cached_live_series_keeps_live_source(monkeypatch, end):
    """
    Request the same series twice with mocked yfinance returning valid data.
    The second response must retain source == 'live' and have from_cache == True.
    """
    dates = pd.date_range(end=end or datetime.now(), periods=100, freq="B")
    mock_df = pd.DataFrame({
        "Close": [100.0 + i * 0.5 for i in range(len(dates))]
    }, index=dates)

    class MockTicker:
        def __init__(self, ticker):
            self.ticker = ticker
            self.info = {"shortName": "Mock Real Corp"}
        def history(self, period="2y", interval="1d"):
            return mock_df

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", MockTicker)

    # First call - live fetch
    res1 = client.get("/api/data/market?ticker=AAPLTEST&period=2y")
    assert res1.status_code == 200, res1.text
    data1 = res1.json()
    assert data1["source"] == "live"
    assert data1.get("from_cache") is False or data1.get("from_cache") is None

    # Second call - served from cache
    res2 = client.get("/api/data/market?ticker=AAPLTEST&period=2y")
    assert res2.status_code == 200, res2.text
    data2 = res2.json()
    assert data2["source"] == "live", f"Expected source='live' but got '{data2.get('source')}'"
    assert data2.get("from_cache") is True, f"Expected from_cache=True but got '{data2.get('from_cache')}'"
    assert data2.get("cached_at") is not None


def test_cached_synthetic_series_still_rejected_by_backtest(monkeypatch):
    """
    With ALLOW_SYNTHETIC_DATA=True, generate a synthetic series, force it into cache,
    and verify that /api/backtest STILL rejects it with 422 Unprocessable Entity.
    """
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)

    pts = [
        TimeSeriesPoint(
            timestamp=(datetime(2023, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"),
            value=round(100.0 + i * 0.2, 2)
        )
        for i in range(150)
    ]
    synthetic_series = TimeSeriesData(
        id="SYNTHFAIL",
        name="Synthetic Fail Asset",
        type="equity",
        unit="USD",
        points=pts,
        source="synthetic",
        source_detail="Synthetic test series"
    )

    # Force synthetic series into cache for 5y horizon used by backtest
    cache.set("yf_hist_SYNTHFAIL_5y_1d", synthetic_series)

    # Verify that get_history loads it from cache
    fetched = MarketDataFetcher.get_history("SYNTHFAIL", period="5y")
    # In the fixed code, fetched.source must remain 'synthetic'
    # In the old code, fetched.source was overwritten to 'cached'

    resp = client.post("/api/backtest", json={
        "series_id": "SYNTHFAIL",
        "cutoff_date": "2023-04-01",
        "horizon": 20,
        "confidence": 0.95
    })
    assert resp.status_code == 422, f"Expected 422 for cached synthetic backtest, got {resp.status_code}: {resp.text}"
    assert "sintética" in resp.json()["detail"].lower() or "synthetic" in resp.json()["detail"].lower()


def test_cached_synthetic_series_still_rejected_by_correlation(monkeypatch):
    """
    Verify that /api/correlation rejects cached synthetic series with 422.
    """
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)

    pts = [
        TimeSeriesPoint(
            timestamp=(datetime(2023, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"),
            value=round(100.0 + i * 0.2, 2)
        )
        for i in range(150)
    ]
    synthetic_series = TimeSeriesData(
        id="SYNTHCORR",
        name="Synthetic Corr Asset",
        type="equity",
        unit="USD",
        points=pts,
        source="synthetic",
        source_detail="Synthetic test series"
    )

    cache.set("yf_hist_SYNTHCORR_1y_1d", synthetic_series)

    resp = client.post("/api/correlation", json={
        "series_ids": ["SYNTHCORR", "NVDA"],
        "period": "1y",
        "mode": "returns"
    })
    assert resp.status_code == 422, f"Expected 422 for cached synthetic correlation, got {resp.status_code}: {resp.text}"


def test_cached_synthetic_series_still_rejected_by_portfolio_optimize(monkeypatch):
    """
    Verify that /api/portfolio/optimize rejects cached synthetic series with 422.
    """
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)

    pts = [
        TimeSeriesPoint(
            timestamp=(datetime(2022, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"),
            value=round(100.0 + i * 0.2, 2)
        )
        for i in range(300)
    ]
    synthetic_series = TimeSeriesData(
        id="SYNTHOPT",
        name="Synthetic Opt Asset",
        type="equity",
        unit="USD",
        points=pts,
        source="synthetic",
        source_detail="Synthetic test series"
    )

    cache.set("yf_hist_SYNTHOPT_2y_1d", synthetic_series)

    resp = client.post("/api/portfolio/optimize", json={
        "tickers": ["SYNTHOPT", "NVDA"],
        "period": "2y"
    })
    assert resp.status_code == 422, f"Expected 422 for cached synthetic portfolio optimize, got {resp.status_code}: {resp.text}"


def test_cached_synthetic_series_still_rejected_by_portfolio_risk(monkeypatch):
    """
    Verify that /api/portfolio/risk rejects cached synthetic series with 422.
    """
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)

    pts = [
        TimeSeriesPoint(
            timestamp=(datetime(2022, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"),
            value=round(100.0 + i * 0.2, 2)
        )
        for i in range(300)
    ]
    synthetic_series = TimeSeriesData(
        id="SYNTHRISK",
        name="Synthetic Risk Asset",
        type="equity",
        unit="USD",
        points=pts,
        source="synthetic",
        source_detail="Synthetic test series"
    )

    cache.set("yf_hist_SYNTHRISK_2y_1d", synthetic_series)

    resp = client.post("/api/portfolio/risk", json={
        "tickers": ["SYNTHRISK", "NVDA"],
        "period": "2y"
    })
    assert resp.status_code == 422, f"Expected 422 for cached synthetic portfolio risk, got {resp.status_code}: {resp.text}"


def test_cached_fred_series_keeps_source(monkeypatch):
    """
    Verify that FREDDataFetcher preserves source and sets from_cache=True on second fetch.
    """
    monkeypatch.setattr(settings, "FRED_API_KEY", "")
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)

    fetcher = FREDDataFetcher()
    # First fetch - generates reference synthetic series and caches it
    s1 = fetcher.get_series("IPG2211A2N")
    assert s1.source == "synthetic"
    assert s1.from_cache is False

    # Second fetch - served from cache
    s2 = fetcher.get_series("IPG2211A2N")
    assert s2.source == "synthetic", f"Expected source='synthetic' but got '{s2.source}'"
    assert s2.from_cache is True
    assert s2.cached_at is not None


def test_cached_fundamentals_keeps_source(monkeypatch):
    """
    Verify that MarketDataFetcher.get_fundamentals preserves source and sets from_cache=True on cache hit.
    """
    cf_df = pd.DataFrame(
        {"2023": [35_000_000_000]},
        index=["Capital Expenditure"]
    )
    inc_df = pd.DataFrame(
        {"2023": [100_000_000_000]},
        index=["Total Revenue"]
    )

    class MockTicker:
        def __init__(self, sym):
            self.cashflow = cf_df
            self.financials = inc_df

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", MockTicker)

    # First fetch
    metrics1, warns1 = MarketDataFetcher.get_fundamentals(["MSFTTEST"])
    assert len(metrics1) > 0
    assert metrics1[0].source == "live"
    assert metrics1[0].from_cache is False

    # Second fetch - from cache
    metrics2, warns2 = MarketDataFetcher.get_fundamentals(["MSFTTEST"])
    assert len(metrics2) > 0
    assert metrics2[0].source == "live"
    assert metrics2[0].from_cache is True
    assert metrics2[0].cached_at is not None
