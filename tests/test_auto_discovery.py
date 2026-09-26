import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.connection import Base
from backend.database.models import EngineDecisionModel
from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.data_fetcher import MarketDataFetcher
from backend.services import auto_discovery
from backend.services.auto_discovery import AutoDiscoveryEngine
from backend.services.forecast_engine import TimesFMForecastEngine


@pytest.fixture
def db_session():
    """Isolated in-memory SQLite session — never touches the real project DB."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def nvda_fixture_series():
    fix_dir = Path(__file__).parent / "fixtures"
    pts = [TimeSeriesPoint(**p) for p in json.loads((fix_dir / "nvda_daily.json").read_text())]
    return TimeSeriesData(id="NVDA", name="NVIDIA Corp", type="equity", unit="USD", points=pts, source="live")


@pytest.fixture
def isolated_timesfm_singleton():
    TimesFMForecastEngine._instance = None
    yield
    TimesFMForecastEngine._instance = None


def test_new_series_triggers_autodiscovery(db_session, nvda_fixture_series, monkeypatch):
    """A series not in either curated catalog, with enough history, triggers the
    mini-backtest and caches a decision — never silently defaulting to Holt
    without having measured anything, unlike the pre-Variant-B behavior."""
    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *a, **kw: nvda_fixture_series)
    monkeypatch.setattr(auto_discovery.settings, "USE_REAL_TIMESFM", False)  # keep this test fast/deterministic

    assert AutoDiscoveryEngine.get_cached_decision(db_session, "NEWTICKER") is None

    decision = AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=len(nvda_fixture_series.points))

    assert decision is not None
    assert decision.series_id == "NEWTICKER"
    assert decision.engine_choice in ("holt", "timesfm")
    assert decision.mase_holt > 0
    assert decision.n_points_at_evaluation == len(nvda_fixture_series.points)

    # Actually persisted, not just returned in-memory.
    reloaded = AutoDiscoveryEngine.get_cached_decision(db_session, "NEWTICKER")
    assert reloaded is not None
    assert reloaded.engine_choice == decision.engine_choice


def test_cached_decision_not_recomputed(db_session, nvda_fixture_series, monkeypatch):
    """The second call for the same series must NOT re-run the mini-backtest —
    verified by counting BacktestEngine.run_backtest invocations."""
    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *a, **kw: nvda_fixture_series)
    monkeypatch.setattr(auto_discovery.settings, "USE_REAL_TIMESFM", False)

    call_count = {"n": 0}
    from backend.services.backtest_engine import BacktestEngine
    original_run_backtest = BacktestEngine.run_backtest

    def counting_run_backtest(*args, **kwargs):
        call_count["n"] += 1
        return original_run_backtest(*args, **kwargs)

    monkeypatch.setattr(BacktestEngine, "run_backtest", staticmethod(counting_run_backtest))

    n_points = len(nvda_fixture_series.points)
    AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=n_points)
    first_call_count = call_count["n"]
    assert first_call_count > 0, "the first call must have run the mini-backtest"

    AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=n_points)
    assert call_count["n"] == first_call_count, (
        "a cached, non-stale decision must not trigger the mini-backtest again"
    )


def test_stale_decision_recomputed_after_ttl(db_session, nvda_fixture_series, monkeypatch):
    """Forcing an old evaluated_at date must trigger re-evaluation, even though
    n_points hasn't grown — the market can change regime independent of new data."""
    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *a, **kw: nvda_fixture_series)
    monkeypatch.setattr(auto_discovery.settings, "USE_REAL_TIMESFM", False)

    n_points = len(nvda_fixture_series.points)
    AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=n_points)

    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=auto_discovery.DECISION_TTL_DAYS + 5)
    cached = AutoDiscoveryEngine.get_cached_decision(db_session, "NEWTICKER")
    cached.evaluated_at = stale_cutoff.replace(tzinfo=None)
    db_session.commit()

    call_count = {"n": 0}
    from backend.services.backtest_engine import BacktestEngine
    original_run_backtest = BacktestEngine.run_backtest

    def counting_run_backtest(*args, **kwargs):
        call_count["n"] += 1
        return original_run_backtest(*args, **kwargs)

    monkeypatch.setattr(BacktestEngine, "run_backtest", staticmethod(counting_run_backtest))

    decision = AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=n_points)
    assert call_count["n"] > 0, "a stale (TTL-expired) decision must be re-evaluated"
    assert decision.evaluated_at.replace(tzinfo=None) > stale_cutoff.replace(tzinfo=None)


def test_short_history_series_skips_autodiscovery(db_session):
    """Below MIN_HISTORY_FOR_AUTODISCOVERY, decide() returns None without
    attempting any backtest — the caller (EngineSelector) falls back to the
    existing cold-start path instead."""
    result = AutoDiscoveryEngine.decide(db_session, "TINYHISTORY", n_points=45)
    assert result is None
    assert AutoDiscoveryEngine.get_cached_decision(db_session, "TINYHISTORY") is None


def test_mini_backtest_failure_does_not_break_the_forecast(db_session, monkeypatch):
    """A failed mini-backtest (e.g. data provider error) must not propagate and
    break the actual /forecast request that triggered it — decide() returns
    None (or a stale cached decision) instead of raising."""
    def failing_get_history(*a, **kw):
        raise ValueError("simulated data provider failure")

    monkeypatch.setattr(MarketDataFetcher, "get_history", failing_get_history)

    result = AutoDiscoveryEngine.decide(db_session, "BROKENTICKER", n_points=200)
    assert result is None
    assert AutoDiscoveryEngine.get_cached_decision(db_session, "BROKENTICKER") is None


def test_engine_selector_reason_reflects_calibration_disqualification(db_session):
    """
    Regression test for a real bug found via manual UI testing: when TimesFM
    has the LOWER (better) MASE but is disqualified by the coverage-calibration
    guard (see auto_discovery.MAX_ACCEPTABLE_COVERAGE_GAP_PP), engine_choice is
    correctly "holt" — but the reason text must say TimesFM actually won on
    MASE and lost on calibration, NOT "Holt ganó MASE X vs TimesFM Y" (which
    would be literally false when Y < X, i.e. TimesFM's MASE was better).
    """
    from backend.services.engine_selector import EngineSelector

    decision = EngineDecisionModel(
        series_id="CEG",
        engine_choice="holt",  # correctly disqualified by calibration guard
        mase_holt=5.477,
        mase_timesfm=4.237,  # BETTER than Holt's — this is the bug trigger
        n_points_at_evaluation=170,
    )
    db_session.add(decision)
    db_session.commit()

    points = [TimeSeriesPoint(timestamp=f"2020-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}", value=100.0 + i * 0.3) for i in range(200)]
    res = EngineSelector._try_auto_discovery(
        db_session, "CEG", "equity", points, len(points), horizon=10, confidence=0.95, freq="D",
    )

    assert res is not None
    assert res.model_name == "damped-holt-mle"
    assert "Holt ganó MASE" not in res.engine_selection_reason, (
        "must not claim Holt won on MASE when TimesFM's MASE (4.237) was actually lower than Holt's (5.477)"
    )
    assert "TimesFM tuvo mejor MASE" in res.engine_selection_reason
    assert "calibra" in res.engine_selection_reason.lower()


def test_engine_selector_falls_through_to_default_when_autodiscovery_unavailable(monkeypatch):
    """End-to-end: EngineSelector.select() with a db session, for a series
    outside both curated catalogs, where the mini-backtest fails — must still
    return a normal ForecastResponse (Holt default), not raise."""
    from backend.services.engine_selector import EngineSelector

    def failing_get_history(*a, **kw):
        raise ValueError("simulated data provider failure")

    monkeypatch.setattr(MarketDataFetcher, "get_history", failing_get_history)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    points = [TimeSeriesPoint(timestamp=f"2020-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}", value=100.0 + i * 0.3) for i in range(200)]
    res = EngineSelector.select(points, series_id="BROKENTICKER", series_type="equity", horizon=10, db=db)

    assert res.model_name == "damped-holt-mle"
    assert "Holt (default)" in res.engine_selection_reason
    db.close()


# ---------------------------------------------------------------------------
# "No evaluado" (TimesFM unavailable at evaluation time) != "Holt ganó".
# The backtest and TimesFM availability are mocked: no weights, no data fetch.
# ---------------------------------------------------------------------------

_FAKE_TIMESFM = object()
_FAKE_CUTOFFS = ["2024-01-31", "2024-06-30", "2024-11-30"]


def _mock_mini_backtest(monkeypatch, *, tfm_available, mase_holt=1.0, mase_tfm=0.5):
    """Mocks TimesFM availability, the cutoffs and BacktestEngine.run_backtest.
    Returns (state, calls): flip state["tfm_available"] to simulate TimesFM
    becoming available; calls counts run_backtest calls per engine."""
    from backend.services.backtest_engine import BacktestEngine
    from types import SimpleNamespace

    state = {"tfm_available": tfm_available}
    calls = {"holt": 0, "timesfm": 0}

    monkeypatch.setattr(
        auto_discovery, "_available_timesfm_engine",
        lambda: _FAKE_TIMESFM if state["tfm_available"] else None,
    )
    monkeypatch.setattr(AutoDiscoveryEngine, "_pick_cutoffs", staticmethod(lambda series_id, is_macro: _FAKE_CUTOFFS))

    def fake_run_backtest(*, engine_override, **kwargs):
        engine = "timesfm" if engine_override is _FAKE_TIMESFM else "holt"
        calls[engine] += 1
        mase = mase_tfm if engine == "timesfm" else mase_holt
        return SimpleNamespace(metrics=SimpleNamespace(mase=mase), interval_coverage=90.0)

    monkeypatch.setattr(BacktestEngine, "run_backtest", staticmethod(fake_run_backtest))
    return state, calls


def test_unevaluated_decision_reevaluated_once_timesfm_available(db_session, monkeypatch):
    """Evaluated without TimesFM -> stored as not evaluated (mase_timesfm NULL).
    Once TimesFM is available, the next request re-evaluates it even though the
    TTL is nowhere near expired and the series hasn't grown."""
    state, calls = _mock_mini_backtest(monkeypatch, tfm_available=False, mase_holt=1.0, mase_tfm=0.5)

    first = AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=500)
    assert first.engine_choice == "holt"
    assert first.mase_timesfm is None
    assert calls == {"holt": 3, "timesfm": 0}

    state["tfm_available"] = True
    second = AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=500)

    assert calls == {"holt": 6, "timesfm": 3}, "must re-run the mini-backtest, now with TimesFM"
    assert second.mase_timesfm == 0.5
    assert second.engine_choice == "timesfm"
    stored = AutoDiscoveryEngine.get_cached_decision(db_session, "NEWTICKER")
    assert stored.mase_timesfm == 0.5 and stored.engine_choice == "timesfm"


def test_unevaluated_decision_not_rerun_while_timesfm_unavailable(db_session, monkeypatch):
    """Without TimesFM, repeated requests reuse the cached (not evaluated)
    decision: re-running would just be Holt-only again, a useless cost."""
    _, calls = _mock_mini_backtest(monkeypatch, tfm_available=False)

    for _ in range(5):
        decision = AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=500)
        assert decision.mase_timesfm is None

    assert calls == {"holt": 3, "timesfm": 0}, "only the first request may run the mini-backtest"


def test_real_holt_win_respects_regular_ttl(db_session, monkeypatch):
    """Holt actually beat TimesFM (mase_timesfm is a real number): TimesFM being
    available is not a reason to re-evaluate — only the regular TTL is."""
    _, calls = _mock_mini_backtest(monkeypatch, tfm_available=True, mase_holt=0.8, mase_tfm=1.2)

    first = AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=500)
    assert first.engine_choice == "holt"
    assert first.mase_timesfm == 1.2
    assert calls == {"holt": 3, "timesfm": 3}

    for _ in range(3):
        AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=500)
    assert calls == {"holt": 3, "timesfm": 3}, "within the TTL a real Holt win must stay cached"

    cached = AutoDiscoveryEngine.get_cached_decision(db_session, "NEWTICKER")
    cached.evaluated_at = (datetime.now(timezone.utc) - timedelta(days=auto_discovery.DECISION_TTL_DAYS + 1)).replace(tzinfo=None)
    db_session.commit()

    AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=500)
    assert calls == {"holt": 6, "timesfm": 6}, "past the TTL it is re-evaluated as before"


def test_no_cutoffs_is_a_failure_not_an_unevaluated_decision(db_session, monkeypatch):
    """With no cutoff the old code cached mean([]) = NaN as a "holt" decision
    with mase_timesfm=None, indistinguishable from "TimesFM unavailable". Now it
    is a failed mini-backtest: nothing cached, the caller falls back."""
    _mock_mini_backtest(monkeypatch, tfm_available=True)
    monkeypatch.setattr(AutoDiscoveryEngine, "_pick_cutoffs", staticmethod(lambda series_id, is_macro: []))

    assert AutoDiscoveryEngine.decide(db_session, "NEWTICKER", n_points=500) is None
    assert AutoDiscoveryEngine.get_cached_decision(db_session, "NEWTICKER") is None


def test_timesfm_availability_check_loads_at_most_once(monkeypatch, isolated_timesfm_singleton):
    """The availability check runs on cached-decision requests, so it must not
    load the ~900MB of weights each time: at most once per process, and never
    with USE_REAL_TIMESFM=false."""
    loads = {"n": 0}

    def fake_load_model(self):
        loads["n"] += 1
        self._model = None  # simulates weights that fail to load

    monkeypatch.setattr(TimesFMForecastEngine, "_load_model", fake_load_model)

    monkeypatch.setattr(auto_discovery.settings, "USE_REAL_TIMESFM", False)
    assert TimesFMForecastEngine.is_available() is False
    assert TimesFMForecastEngine._instance is None, "must not even build the singleton"

    monkeypatch.setattr(auto_discovery.settings, "USE_REAL_TIMESFM", True)
    for _ in range(5):
        assert TimesFMForecastEngine.is_available() is False
    assert loads["n"] == 1


def test_engine_selector_reason_for_unevaluated_decision(db_session, monkeypatch):
    """The reason must say TimesFM wasn't evaluated and that it will be
    re-evaluated — never "Holt ganó", since Holt wasn't compared at all."""
    from backend.services.engine_selector import EngineSelector

    # Still unavailable, so the cached decision is served as-is (no real
    # TimesFM load, no re-evaluation against live data).
    monkeypatch.setattr(auto_discovery, "_available_timesfm_engine", lambda: None)

    db_session.add(EngineDecisionModel(
        series_id="NOTFM", engine_choice="holt", mase_holt=0.9, mase_timesfm=None, n_points_at_evaluation=200,
    ))
    db_session.commit()

    points = [TimeSeriesPoint(timestamp=f"2020-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}", value=100.0 + i * 0.3) for i in range(200)]
    res = EngineSelector._try_auto_discovery(
        db_session, "NOTFM", "equity", points, len(points), horizon=10, confidence=0.95, freq="D",
    )

    assert "Holt ganó" not in res.engine_selection_reason
    assert "TimesFM no evaluado" in res.engine_selection_reason
    assert "re-evalúa" in res.engine_selection_reason
