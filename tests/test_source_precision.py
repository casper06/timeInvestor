"""
2.9: values are loaded and processed at the source's precision; nothing is
rounded on load. Fake FRED/yfinance responses with 4+ decimals.
"""
import pandas as pd
import pytest
import yfinance as yf

from backend.config import settings
from backend.services import data_fetcher
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import FREDDataFetcher, MarketDataFetcher
from backend.services.forecast_engine import DampedHoltForecastEngine


@pytest.fixture(autouse=True)
def _empty_cache():
    data_fetcher.cache.clear()
    yield
    data_fetcher.cache.clear()


def _fake_fred(monkeypatch, values):
    """FRED answers most recent first; `values` is chronological."""
    import httpx
    monkeypatch.setattr(settings, "FRED_API_KEY", "fake-test-key")
    obs = [{"date": f"{2000 + i // 12:04d}-{i % 12 + 1:02d}-01", "value": v} for i, v in enumerate(values)]

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"observations": list(reversed(obs))}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    return obs


def test_fred_values_keep_their_decimals(monkeypatch):
    _fake_fred(monkeypatch, ["-0.52431", "0.12345", "103.0736", "."])
    series = FREDDataFetcher().get_series("NFCI")
    assert [p.value for p in series.points] == [-0.52431, 0.12345, 103.0736]  # "." (missing) skipped


def test_yfinance_close_keeps_its_decimals(monkeypatch):
    idx = pd.date_range("2026-01-05", periods=3, freq="B")
    df = pd.DataFrame({"Close": [187.23999786376953, 188.1234, 189.98765]}, index=idx)

    class FakeTicker:
        def __init__(self, *a, **k):
            self.info = {"shortName": "X"}

        def history(self, *a, **k):
            return df

    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    series = MarketDataFetcher.get_history("XPREC", period="1y")
    assert [p.value for p in series.points] == [187.23999786376953, 188.1234, 189.98765]


def test_a_value_with_many_decimals_reaches_the_engine_intact(monkeypatch):
    values = [f"{0.5 + 0.00137 * i + (0.00011 if i % 2 else 0):.5f}" for i in range(80)]
    _fake_fred(monkeypatch, values)
    seen = {}

    class Spy(DampedHoltForecastEngine):
        def forecast(self, points, horizon=30, confidence=0.95, freq="D"):
            seen["train"] = [p.value for p in points]
            return super().forecast(points, horizon, confidence, freq)

    cutoff = f"{2000 + 59 // 12:04d}-{59 % 12 + 1:02d}-01"
    BacktestEngine.run_backtest("NFCIX", cutoff, horizon=12, is_macro=True, engine_override=Spy())
    assert seen["train"][:60] == [float(v) for v in values[:60]]
    assert any(len(v.split(".")[1]) >= 5 for v in values[:60])  # the test really has 5-decimal values
