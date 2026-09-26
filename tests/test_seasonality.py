"""
Seasonality detection and the seasonal naive benchmark (item 3.0a).

All series here are SYNTHETIC with known structure, generated only for these
tests (never product data): a monthly series with a real annual cycle, a
trending one without a cycle, a random walk, and a daily one.
"""
from datetime import date, timedelta

import numpy as np
import pytest

from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import FREDDataFetcher, MarketDataFetcher
from backend.services.forecast_engine import DampedHoltForecastEngine
from backend.services.seasonality import (
    detect_seasonality,
    infer_frequency,
    seasonal_naive_forecast,
    seasonal_scale,
)


def _monthly(values, start=(2000, 1)):
    y, m = start
    pts = []
    for v in values:
        pts.append(TimeSeriesPoint(timestamp=f"{y:04d}-{m:02d}-01", value=float(v)))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return pts


def _business_daily(values, start=date(2020, 1, 1)):
    pts, d = [], start
    for v in values:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        pts.append(TimeSeriesPoint(timestamp=d.isoformat(), value=float(v)))
        d += timedelta(days=1)
    return pts


def seasonal_trend_series(n=240, seed=0):
    """Known annual cycle (amplitude 8% of level) on an upward trend + noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    level = 100 * np.exp(0.003 * t)
    cycle = 1 + 0.08 * np.sin(2 * np.pi * t / 12)
    return level * cycle * np.exp(rng.normal(0, 0.01, n))


def trend_only_series(n=240, seed=0):
    """Strong trend, no cycle: on levels its ACF(12) is high; it must NOT pass."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return 100 * np.exp(0.005 * t) * np.exp(rng.normal(0, 0.01, n))


def random_walk_series(n=240, seed=0):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))


# --- frequency -------------------------------------------------------------

def test_infer_frequency():
    assert infer_frequency([p.timestamp for p in _monthly(range(30))]) == "monthly"
    assert infer_frequency([p.timestamp for p in _business_daily(range(30))]) == "daily"
    quarterly = [f"{2000 + i // 4}-{(i % 4) * 3 + 1:02d}-01" for i in range(20)]
    assert infer_frequency(quarterly) == "quarterly"


# --- detection -------------------------------------------------------------

def test_detects_known_annual_cycle():
    info = detect_seasonality(_monthly(seasonal_trend_series()))
    assert info.frequency == "monthly" and info.period == 12
    assert info.is_seasonal is True
    assert info.acf_at_period > info.threshold


@pytest.mark.parametrize("seed", range(5))
def test_trend_without_cycle_is_not_seasonal(seed):
    """The reason the test runs on differences: on levels a pure trend has a
    high ACF at lag 12 and would pass as seasonal."""
    series = trend_only_series(seed=seed)
    levels = series - series.mean()
    acf12_levels = float(np.dot(levels[:-12], levels[12:]) / np.dot(levels, levels))
    assert acf12_levels > 0.8  # a levels-based test would say "seasonal"

    assert detect_seasonality(_monthly(series)).is_seasonal is False


def test_random_walk_is_not_seasonal():
    assert detect_seasonality(_monthly(random_walk_series())).is_seasonal is False


def test_daily_series_is_not_evaluated():
    info = detect_seasonality(_business_daily(seasonal_trend_series(n=300)))
    assert info.frequency == "daily"
    assert info.period is None and info.is_seasonal is False
    assert "No evaluada" in info.reason


def test_short_history_is_not_evaluated():
    info = detect_seasonality(_monthly(seasonal_trend_series(n=30)))  # 29 diffs < 3*12
    assert info.period == 12 and info.is_seasonal is False
    assert "insuficiente" in info.reason


# --- seasonal naive and its scale -------------------------------------------

def test_seasonal_naive_repeats_last_season():
    train = list(range(1, 25))  # two "years": 1..12, 13..24
    fc = seasonal_naive_forecast(train, horizon=15, m=12)
    assert list(fc[:12]) == list(range(13, 25))
    assert list(fc[12:]) == [13, 14, 15]  # wraps to the same season again


def test_seasonal_scale():
    y = [10, 20, 30, 12, 21, 33]  # m=3: |12-10|, |21-20|, |33-30| -> mean 2
    assert seasonal_scale(y, 3) == pytest.approx(2.0)
    assert seasonal_scale([1, 2, 3], 3) is None


# --- run_backtest ----------------------------------------------------------

def _patch_fred(monkeypatch, pts):
    series = TimeSeriesData(id="SYNTH", name="synthetic", type="macro", unit="idx", points=pts, source="live")
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, *a, **kw: series)


def test_backtest_adds_seasonal_benchmark_without_touching_mase(monkeypatch):
    pts = _monthly(seasonal_trend_series())
    _patch_fred(monkeypatch, pts)
    cutoff = pts[200].timestamp

    res = BacktestEngine.run_backtest(
        series_id="SYNTH", cutoff_date=cutoff, horizon=24, is_macro=True,
        engine_override=DampedHoltForecastEngine(),
    )

    assert res.seasonality.is_seasonal and res.seasonality.period == 12
    assert res.seasonal_naive_metrics is not None
    assert res.metrics.mase_seasonal is not None
    assert res.naive_metrics.mase_seasonal is not None

    # The 1-step MASE is still the 1-step MASE: same scale as before 3.0a.
    train = np.array([p.value for p in pts[:201]])
    expected_mase = res.metrics.mae / np.mean(np.abs(np.diff(train)))
    assert res.metrics.mase == pytest.approx(expected_mase, abs=2e-3)

    # Holt ignores the cycle; on a strongly seasonal series the seasonal naive
    # should win, and the verdict has to say so.
    assert res.seasonal_naive_metrics.mae < res.metrics.mae
    assert "NO supera al naive estacional" in res.verdict


def test_backtest_non_seasonal_monthly_has_no_seasonal_fields(monkeypatch):
    pts = _monthly(random_walk_series())
    _patch_fred(monkeypatch, pts)

    res = BacktestEngine.run_backtest(
        series_id="SYNTH", cutoff_date=pts[200].timestamp, horizon=24, is_macro=True,
        engine_override=DampedHoltForecastEngine(),
    )

    assert res.seasonality.is_seasonal is False
    assert res.seasonal_naive_metrics is None
    assert res.metrics.mase_seasonal is None and res.naive_metrics.mase_seasonal is None
    assert "naive estacional" not in res.verdict


def test_backtest_daily_series_reports_not_evaluated(monkeypatch):
    pts = _business_daily(random_walk_series(n=300))
    series = TimeSeriesData(id="DAILY", name="synthetic", type="equity", unit="USD", points=pts, source="live")
    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *a, **kw: series)

    res = BacktestEngine.run_backtest(
        series_id="DAILY", cutoff_date=pts[250].timestamp, horizon=30,
        engine_override=DampedHoltForecastEngine(),
    )

    assert res.seasonality.frequency == "daily" and res.seasonality.period is None
    assert res.seasonal_naive_metrics is None
