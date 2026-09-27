"""
2.11: the engines return forecast and bands at full precision, and the
backtest returns unrounded metrics; rounding is presentation only.
Synthetic series built for these tests.
"""
import numpy as np

from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import FREDDataFetcher
from backend.services.forecast_engine import DampedHoltForecastEngine, HoltWintersForecastEngine
from tests.test_timesfm_band import FakeTimesFMModel, fake_timesfm  # noqa: F401  (fixture)


def _has_more_than(values, decimals):
    return any(abs(v - round(v, decimals)) > 1e-12 for v in values)


def _monthly(values):
    return [TimeSeriesPoint(timestamp=f"{2000 + i // 12:04d}-{i % 12 + 1:02d}-01", value=float(v))
            for i, v in enumerate(values)]


def _small_walk(n=200, seed=4):
    rng = np.random.default_rng(seed)
    return -0.5 + np.cumsum(rng.normal(0, 0.013, n))    # NFCI-like: around -0.5, moves of hundredths


def test_holt_forecast_and_band_keep_full_precision():
    res = DampedHoltForecastEngine().forecast(_monthly(_small_walk()), horizon=12, confidence=0.8, freq="M")
    for arr in (res.values, res.lower_bound, res.upper_bound):
        assert _has_more_than(arr, 2)


def test_holt_winters_keeps_full_precision():
    rng = np.random.default_rng(1)
    t = np.arange(240)
    vals = 100 * np.exp(0.002 * t) * (1 + 0.10 * np.sin(2 * np.pi * t / 12)) * np.exp(rng.normal(0, 0.01, 240))
    res = HoltWintersForecastEngine().forecast(_monthly(vals), horizon=12, confidence=0.8, freq="M")
    assert _has_more_than(res.values, 2) and _has_more_than(res.lower_bound, 2)


class _OffsetModel(FakeTimesFMModel):
    def forecast(self, horizon, inputs):
        point, q = super().forecast(horizon, inputs)
        return point + 0.123456, q + 0.123456


def test_timesfm_keeps_full_precision(fake_timesfm):  # noqa: F811
    res = fake_timesfm(_OffsetModel()).forecast(_monthly(np.linspace(90, 110, 80)), horizon=12, confidence=0.8)
    assert not res.is_fallback
    assert res.values[0] == 100.123456 and res.lower_bound[0] == 60.123456 and res.upper_bound[0] == 140.123456


def test_backtest_metrics_and_forecast_are_not_rounded(monkeypatch):
    vals = _small_walk()
    series = TimeSeriesData(id="SMALL", name="s", type="macro", unit="", points=_monthly(vals), source="live")
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, sid, *a, **k: series)
    res = BacktestEngine.run_backtest("SMALL", series.points[150].timestamp, horizon=12, is_macro=True,
                                      engine_override=DampedHoltForecastEngine())
    assert _has_more_than([res.metrics.mae, res.naive_metrics.mae], 2)
    assert _has_more_than([res.metrics.mase], 3)
    assert _has_more_than(res.future_predicted_values, 2)
