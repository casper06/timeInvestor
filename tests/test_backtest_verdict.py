"""
Reality Check verdict: it leads with the MORE DEMANDING naive, the one with
the lower error on that cutoff (3.5's criterion), and gives the other one
after it as secondary data. Synthetic monthly series with a known answer.
"""
import numpy as np

from backend.schemas.models import TimeSeriesData
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import FREDDataFetcher
from backend.services.forecast_engine import DampedHoltForecastEngine
from tests.test_seasonality import _monthly, random_walk_series, seasonal_trend_series

RW, SN = "random walk", "naive estacional"


def _run(monkeypatch, values, horizon):
    pts = _monthly(values)
    series = TimeSeriesData(id="SYNTH", name="synthetic", type="macro", unit="idx", points=pts, source="live")
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, *a, **kw: series)
    return BacktestEngine.run_backtest(series_id="SYNTH", cutoff_date=pts[200].timestamp, horizon=horizon,
                                       is_macro=True, engine_override=DampedHoltForecastEngine())


def test_strong_cycle_leads_with_the_seasonal_naive(monkeypatch):
    res = _run(monkeypatch, seasonal_trend_series(), 24)
    assert res.seasonal_naive_metrics.mae < res.naive_metrics.mae
    assert res.verdict.startswith("Frente al naive más exigente en este corte, el modelo NO supera al naive estacional")
    assert res.verdict.index(SN) < res.verdict.index(RW)
    assert "Dato secundario: el modelo NO supera al random walk" in res.verdict


def test_strong_trend_leads_with_the_random_walk(monkeypatch):
    """A seasonal series whose trend makes last year's value a poor guess: the
    random walk is the more demanding naive and goes first."""
    rng = np.random.default_rng(3)
    t = np.arange(240)
    values = 100 * np.exp(0.02 * t) * (1 + 0.03 * np.sin(2 * np.pi * t / 12)) * np.exp(rng.normal(0, 0.005, 240))
    res = _run(monkeypatch, values, 3)
    assert res.seasonality.is_seasonal
    assert res.naive_metrics.mae < res.seasonal_naive_metrics.mae
    assert res.verdict.startswith("Frente al naive más exigente en este corte, el modelo supera al random walk")
    assert res.verdict.index(RW) < res.verdict.index(SN)
    assert "Dato secundario: el modelo supera al naive estacional" in res.verdict


def test_non_seasonal_names_only_the_random_walk(monkeypatch):
    res = _run(monkeypatch, random_walk_series(), 24)
    assert res.seasonal_naive_metrics is None
    assert res.verdict.startswith("El modelo")
    assert RW in res.verdict and SN not in res.verdict
    assert "Dato secundario" not in res.verdict and "más exigente" not in res.verdict
    assert "precio" not in res.verdict.lower()
    assert res.unit == "idx"   # the MAE's unit travels with the result (the report doesn't borrow another series')
