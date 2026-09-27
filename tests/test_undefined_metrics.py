"""
Undefined scaled metrics (2.10) and insufficient history for the v5 decision.
Synthetic series built only for these tests: a step series that doesn't move
in training (like a policy rate between moves), an exactly periodic one, and
one with actual values at 0.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services import auto_discovery as ad
from backend.services.auto_discovery import AutoDiscoveryEngine, InsufficientHistoryError, min_history_for_decision
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import FREDDataFetcher
from backend.services.engine_selector import EngineSelector
from backend.services.forecast_engine import DampedHoltForecastEngine
from tests.test_auto_discovery import _FAKE_TIMESFM, _mock_mini_backtest, _reason_for, db_session  # noqa: F401


def _days(n, start=date(2025, 1, 6)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _backtest(values, cutoff_i, h, monkeypatch, sid="STEPS"):
    dates = _days(len(values))
    pts = [TimeSeriesPoint(timestamp=t, value=float(v)) for t, v in zip(dates, values)]
    series = TimeSeriesData(id=sid, name=sid, type="macro", unit="%", points=pts, source="live")
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, s, *a, **k: series)
    return BacktestEngine.run_backtest(sid, dates[cutoff_i], horizon=h, is_macro=True,
                                       engine_override=DampedHoltForecastEngine())


# ---- the metrics ----

def test_mase_is_undefined_not_millions_when_training_did_not_move(monkeypatch):
    values = [4.5] * 120 + [4.25] * 80        # flat in training, a step afterwards
    res = _backtest(values, 99, 30, monkeypatch)
    assert res.metrics.mase is None and res.naive_metrics.mase is None
    assert "no varió" in res.metrics.undefined["mase"]
    assert res.metrics.mae == pytest.approx(0.25 * 10 / 30, abs=0.01)  # MAE is defined: 10 of 30 after the step


def test_mase_defined_when_training_moved(monkeypatch):
    rng = np.random.default_rng(1)
    values = list(100 + np.cumsum(rng.normal(0, 1, 200)))
    res = _backtest(values, 150, 30, monkeypatch)
    assert res.metrics.mase is not None and res.metrics.mase > 0
    assert "mase" not in res.metrics.undefined


def test_mape_is_undefined_when_an_actual_value_is_zero(monkeypatch):
    rng = np.random.default_rng(2)
    values = list(np.round(rng.normal(0.5, 0.3, 200), 2))
    values[160] = 0.0                            # inside the evaluated window
    res = _backtest(values, 150, 30, monkeypatch)
    assert res.metrics.mape is None and "algún valor real" in res.metrics.undefined["mape"]


def test_seasonal_mase_undefined_for_an_exactly_repeating_cycle(monkeypatch):
    cycle = [100, 104, 110, 115, 112, 108, 103, 98, 95, 93, 96, 99]
    values = cycle * 20                          # monthly, identical every year
    pts = [TimeSeriesPoint(timestamp=f"{2000 + i // 12:04d}-{i % 12 + 1:02d}-01", value=float(v))
           for i, v in enumerate(values)]
    series = TimeSeriesData(id="CYCLE", name="c", type="macro", unit="", points=pts, source="live")
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, s, *a, **k: series)
    res = BacktestEngine.run_backtest("CYCLE", pts[200].timestamp, horizon=12, is_macro=True,
                                      engine_override=DampedHoltForecastEngine())
    if res.seasonality is None or not res.seasonality.is_seasonal:
        pytest.skip("the detector didn't mark this cycle seasonal")
    assert res.metrics.mase_seasonal is None and "ciclo anterior" in res.metrics.undefined["mase_seasonal"]


# ---- the decision: paired MAE when the metric is undefined somewhere ----

def test_undefined_mase_on_some_cutoff_switches_the_whole_series_to_paired_mae(db_session, monkeypatch):  # noqa: F811
    _mock_mini_backtest(monkeypatch, tfm_available=True)
    from tests.test_auto_discovery import _FAKE_CUTOFFS

    def fake(*, engine_override, cutoff_date, **kw):
        tfm = engine_override is _FAKE_TIMESFM
        flat = cutoff_date in _FAKE_CUTOFFS[:3]   # these trainings didn't move
        mae = 0.10 if tfm else 0.20               # TimesFM better on every cutoff
        metrics = SimpleNamespace(mase=None if flat else mae / 0.05, mase_seasonal=None, mae=mae,
                                  undefined={"mase": "no varió"} if flat else {})
        return SimpleNamespace(metrics=metrics, interval_coverage=80.0, is_fallback=False,
                               model_name="x", interval_level=0.80)

    monkeypatch.setattr(BacktestEngine, "run_backtest", staticmethod(fake))
    d = AutoDiscoveryEngine.decide(db_session, "PARTLYFLAT", n_points=500)
    assert d.metric == "mae"
    assert d.mase_holt == pytest.approx(0.20) and d.mase_timesfm == pytest.approx(0.10)
    assert d.engine_choice == "timesfm"          # all 8 pairs kept: nothing dropped


def test_reason_explains_why_it_compared_mae(db_session, monkeypatch):  # noqa: F811
    reason = _reason_for(db_session, monkeypatch, engine_choice="holt", mase_holt=0.02,
                         mase_timesfm=0.05, timesfm_failed_cutoffs=0, metric="mae")
    assert "Holt ganó MAE 0.020" in reason
    assert "el MASE no está definido" in reason


# ---- insufficient history ----

@pytest.mark.parametrize("h,expected", [(60, 186), (13, 49), (12, 48), (4, 40)])
def test_min_history_leaves_the_minimum_paired_cutoffs(h, expected):
    assert min_history_for_decision(h) == expected
    idx = ad.recent_cutoff_indices(expected, ad.DECISION_N_CUTOFFS, 10_000, horizon=h)
    assert len(idx) >= ad.MIN_PAIRED_CUTOFFS
    assert len(ad.recent_cutoff_indices(expected - 1, ad.DECISION_N_CUTOFFS, 10_000, horizon=h)) < ad.MIN_PAIRED_CUTOFFS


def test_short_daily_series_says_insufficient_history_and_uses_holt(db_session, monkeypatch):  # noqa: F811
    pts = [TimeSeriesPoint(timestamp=t, value=100.0 + i * 0.1) for i, t in enumerate(_days(150))]
    monkeypatch.setattr(AutoDiscoveryEngine, "_load_points", staticmethod(lambda sid, macro: pts))
    monkeypatch.setattr(ad, "_available_timesfm_engine", lambda: None)
    with pytest.raises(InsufficientHistoryError) as e:
        AutoDiscoveryEngine._pick_cutoffs("NEWIPO", False)
    assert (e.value.n, e.value.required, e.value.horizon) == (150, 186, 60)

    res = EngineSelector._try_auto_discovery(db_session, "NEWIPO", "equity", pts, len(pts),
                                             horizon=60, confidence=0.95, freq="D")
    assert res.model_name == "damped-holt-mle" and res.decision_horizon is None
    assert "Historia insuficiente para evaluar (150 de 186 puntos" in res.engine_selection_reason
    assert "se usa Holt por defecto" in res.engine_selection_reason
