"""
Horizon in the series' own unit (item 4.14). Synthetic series with known
dates, generated only for these tests.
"""
import asyncio
from datetime import date, timedelta

import numpy as np
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.models import InterpretationContext, TimeSeriesData, TimeSeriesPoint
from backend.services import auto_discovery
from backend.services.auto_discovery import AutoDiscoveryEngine
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import FREDDataFetcher
from backend.services.engine_selector import EngineSelector
from backend.services.forecast_engine import DampedHoltForecastEngine
from backend.services.horizons import canonical_horizon, format_horizon, resolve_frequency
from backend.services.llm_router import MockLLMClient
from tests.test_auto_discovery import _mock_mini_backtest, db_session  # noqa: F401  (fixture)

client = TestClient(app)


def _walk(n, seed=3):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0.001, 0.01, n)))


def _monthly(n=240, start_year=2006):
    return [{"timestamp": f"{start_year + i // 12:04d}-{i % 12 + 1:02d}-01", "value": float(v)}
            for i, v in enumerate(_walk(n))]


def _business_days(n=300, start=date(2025, 1, 6)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return [{"timestamp": t, "value": float(v)} for t, v in zip(out, _walk(n))]


def _quarterly(n=60, start_year=2010):
    return [{"timestamp": f"{start_year + i // 4:04d}-{3 * (i % 4) + 1:02d}-01", "value": float(v)}
            for i, v in enumerate(_walk(n))]


# ---- the API: frequency from the dates, default = canonical horizon ----

def test_monthly_series_with_default_horizon_gets_12_monthly_steps():
    pts = _monthly()  # last point 2025-12-01
    res = client.post("/api/forecast", json={"points": pts})
    assert res.status_code == 200
    body = res.json()
    assert body["frequency"] == "monthly" and body["horizon"] == 12
    assert len(body["timestamps"]) == len(body["values"]) == 12
    assert body["timestamps"][0] == "2026-01-01" and body["timestamps"][-1] == "2026-12-01"


def test_dates_decide_over_an_explicit_daily_freq():
    """The pre-4.14 UI sent freq='D' for every series; a monthly series must
    still get monthly dates (INDPRO showed 60 months as 2026-06-02..08-24)."""
    body = client.post("/api/forecast", json={"points": _monthly(), "horizon": 12, "freq": "D"}).json()
    assert body["frequency"] == "monthly"
    assert body["timestamps"][:2] == ["2026-01-01", "2026-02-01"]


def test_daily_series_unchanged_60_business_days():
    pts = _business_days()
    body = client.post("/api/forecast", json={"points": pts, "horizon": 60}).json()
    assert body["frequency"] == "daily" and body["horizon"] == 60
    assert len(body["timestamps"]) == 60
    # Same dates as the engine produced before 4.14 with freq='D'.
    before = DampedHoltForecastEngine()._generate_future_timestamps(pts[-1]["timestamp"], 60, "D")
    assert body["timestamps"] == before
    assert all(date.fromisoformat(t).weekday() < 5 for t in body["timestamps"])


def test_quarterly_series_gets_quarterly_dates():
    body = client.post("/api/forecast", json={"points": _quarterly()}).json()  # last 2024-10-01
    assert body["frequency"] == "quarterly" and body["horizon"] == canonical_horizon("quarterly") == 4
    assert body["timestamps"] == ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01"]


def test_series_data_exposes_its_frequency():
    monthly = TimeSeriesData(id="X", name="X", type="macro", points=[TimeSeriesPoint(**p) for p in _monthly(24)])
    daily = TimeSeriesData(id="Y", name="Y", type="equity", points=[TimeSeriesPoint(**p) for p in _business_days(30)])
    assert monthly.frequency == "monthly" and monthly.model_dump()["frequency"] == "monthly"
    assert daily.frequency == "daily"


def test_resolve_frequency_uses_the_hint_only_when_dates_cant_tell():
    assert resolve_frequency(["2020-01-01", "2020-02-01", "2020-03-01"], "D") == ("monthly", "M")
    assert resolve_frequency(["2020-01-01", "2020-02-01"], "M") == ("monthly", "M")  # < 3 points
    assert resolve_frequency(["2020-01-01", "2020-02-01"], None) == ("daily", "D")


# ---- labels ----

def test_horizon_labels_by_frequency():
    assert format_horizon(60, "daily") == "60 días hábiles"
    assert format_horizon(1, "daily") == "1 día hábil"
    assert format_horizon(13, "weekly") == "13 semanas"
    assert format_horizon(12, "monthly") == "12 meses"
    assert format_horizon(1, "monthly") == "1 mes"
    assert format_horizon(4, "quarterly") == "4 trimestres"
    assert format_horizon(60, None) == "60 pasos"  # unit not recorded


def test_copilot_context_speaks_in_the_series_unit():
    ctx = InterpretationContext(
        thesis="t", active_series_id="INDPRO", last_price=100.0, projected_target=102.0,
        horizon=12, frequency="monthly", lower_bound=95.0, upper_bound=108.0, cagr=2.0,
    )
    resp = asyncio.run(MockLLMClient().interpret_situation(ctx))
    assert "horizonte de 12 meses" in resp.what_data_says
    legacy = ctx.model_copy(update={"horizon": 60, "frequency": None})
    assert "horizonte de 60 días hábiles" in asyncio.run(MockLLMClient().interpret_situation(legacy)).what_data_says


# ---- backtest: frequency from the dates, not the series type ----

def test_backtest_of_a_daily_fred_series_uses_daily_dates(monkeypatch):
    """FRED has daily series (DGS10); 'macro' used to mean monthly steps."""
    pts = [TimeSeriesPoint(**p) for p in _business_days(200)]
    series = TimeSeriesData(id="DGS10", name="10y", type="macro", unit="Percent", points=pts, source="live")
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, sid: series)
    seen = {}

    class Spy(DampedHoltForecastEngine):
        def forecast(self, points, horizon=30, confidence=0.95, freq="D"):
            seen["freq"] = freq
            return super().forecast(points, horizon, confidence, freq)

    res = BacktestEngine.run_backtest("DGS10", pts[150].timestamp, horizon=20, is_macro=True, engine_override=Spy())
    assert seen["freq"] == "D" and res.frequency == "daily"


# ---- the decision records the horizon it was evaluated at ----

def test_auto_discovery_decision_records_its_horizon(db_session, monkeypatch):
    _mock_mini_backtest(monkeypatch, tfm_available=True, mase_holt=1.0, mase_tfm=1.5)
    decision = AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=500)
    assert decision.horizon == auto_discovery.MINI_BACKTEST_HORIZON

    pts = [TimeSeriesPoint(**p) for p in _business_days(300)]
    res = EngineSelector._try_auto_discovery(
        db_session, "NEWTICKER", "equity", pts, len(pts), horizon=60, confidence=0.95, freq="D",
    )
    assert res.decision_horizon == auto_discovery.MINI_BACKTEST_HORIZON


def test_legacy_decision_without_horizon_reads_as_30(db_session):
    from backend.database.models import EngineDecisionModel
    db_session.add(EngineDecisionModel(
        series_id="OLDROW", engine_choice="holt", mase_holt=0.9, mase_timesfm=1.2, n_points_at_evaluation=300,
        criteria_version=auto_discovery.AUTO_DISCOVERY_CRITERIA_VERSION,
    ))
    db_session.commit()
    pts = [TimeSeriesPoint(**p) for p in _business_days(300)]
    res = EngineSelector._try_auto_discovery(
        db_session, "OLDROW", "equity", pts, len(pts), horizon=60, confidence=0.95, freq="D",
    )
    assert res.decision_horizon == 30


def test_catalog_choices_carry_their_benchmark_horizon():
    etf = EngineSelector.select([TimeSeriesPoint(**p) for p in _business_days(300)], series_id="SPY", horizon=60)
    assert etf.decision_horizon == 30
    default = EngineSelector.select([TimeSeriesPoint(**p) for p in _business_days(300)], series_id="ZZZZ", horizon=60)
    assert default.decision_horizon is None  # not chosen by an evaluation
