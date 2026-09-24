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
