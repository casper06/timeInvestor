"""
Holt-Winters engine (item 3.0b). All series are SYNTHETIC with known
structure, generated only for these tests; product data never is.
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import FREDDataFetcher
from backend.services.forecast_engine import (
    DampedHoltForecastEngine,
    HoltWintersForecastEngine,
    NotSeasonalError,
)

client = TestClient(app)


def _monthly(values, start_year=2000):
    return [
        TimeSeriesPoint(timestamp=f"{start_year + i // 12:04d}-{i % 12 + 1:02d}-01", value=float(v))
        for i, v in enumerate(values)
    ]


def seasonal_series(n=240, seed=1):
    """Known annual cycle (10% amplitude) on a mild trend, small noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return 100 * np.exp(0.002 * t) * (1 + 0.10 * np.sin(2 * np.pi * t / 12)) * np.exp(rng.normal(0, 0.01, n))


def random_walk(n=240, seed=1):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))


def _patch_fred(monkeypatch, pts, source="live"):
    series = TimeSeriesData(id="SYNTH", name="synthetic", type="macro", unit="idx", points=pts, source=source)
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, *a, **kw: series)


def test_holt_winters_beats_holt_on_known_seasonal_series(monkeypatch):
    pts = _monthly(seasonal_series())
    _patch_fred(monkeypatch, pts)
    kwargs = dict(series_id="SYNTH", cutoff_date=pts[200].timestamp, horizon=24, is_macro=True)

    hw = BacktestEngine.run_backtest(engine_override=HoltWintersForecastEngine(), **kwargs)
    holt = BacktestEngine.run_backtest(engine_override=DampedHoltForecastEngine(), **kwargs)

    assert hw.metrics.mae < holt.metrics.mae / 2, (hw.metrics.mae, holt.metrics.mae)
    assert hw.model_name.startswith("holt-winters") and "damped-holt" not in hw.model_name
    assert hw.is_fallback is False


def test_forecast_shape_and_log_scale_bounds():
    pts = _monthly(seasonal_series())
    res = HoltWintersForecastEngine().forecast(pts, horizon=12, confidence=0.95, freq="M")
    assert len(res.values) == len(res.lower_bound) == len(res.upper_bound) == 12
    assert all(lo < v < hi for lo, v, hi in zip(res.lower_bound, res.values, res.upper_bound))
    assert all(lo > 0 for lo in res.lower_bound)  # log model: bounds stay positive
    assert res.fitted_params["seasonal_period"] == 12
    assert res.timestamps[0] == "2020-01-01"


def test_not_applied_to_non_seasonal_series():
    with pytest.raises(NotSeasonalError, match="no aplica"):
        HoltWintersForecastEngine().forecast(_monthly(random_walk()), horizon=12, freq="M")


def test_forecast_endpoint_explicit_engine():
    pts = [p.model_dump() for p in _monthly(seasonal_series())]
    ok = client.post("/api/forecast", json={"points": pts, "horizon": 12, "freq": "M", "engine": "holt_winters"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["model_name"].startswith("holt-winters")
    assert "sin pasar por el selector" in body["engine_selection_reason"]

    rw = [p.model_dump() for p in _monthly(random_walk())]
    refused = client.post("/api/forecast", json={"points": rw, "horizon": 12, "freq": "M", "engine": "holt_winters"})
    assert refused.status_code == 422
    assert "no aplica" in refused.json()["detail"]


def test_backtest_endpoint_refuses_non_seasonal(monkeypatch):
    pts = _monthly(random_walk())
    _patch_fred(monkeypatch, pts)
    resp = client.post("/api/backtest", json={
        "series_id": "INDPRO", "cutoff_date": pts[200].timestamp, "horizon": 24, "engine": "holt_winters",
    })
    assert resp.status_code == 422
    assert "no aplica" in resp.json()["detail"]


def test_synthetic_data_never_reaches_holt_winters(monkeypatch):
    """Even with ALLOW_SYNTHETIC_DATA=true, a series whose source is
    "synthetic" is rejected by the backtest endpoint before any engine runs."""
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)
    pts = _monthly(seasonal_series())
    _patch_fred(monkeypatch, pts, source="synthetic")

    calls = {"n": 0}
    real_forecast = HoltWintersForecastEngine.forecast

    def spy(self, *a, **kw):
        calls["n"] += 1
        return real_forecast(self, *a, **kw)

    monkeypatch.setattr(HoltWintersForecastEngine, "forecast", spy)

    resp = client.post("/api/backtest", json={
        "series_id": "INDPRO", "cutoff_date": pts[200].timestamp, "horizon": 24, "engine": "holt_winters",
    })
    assert resp.status_code == 422
    assert "sintética" in resp.json()["detail"]
    assert calls["n"] == 0
