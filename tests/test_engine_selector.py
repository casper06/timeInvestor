import pytest
from pathlib import Path
from backend.config import settings
from backend.schemas.models import TimeSeriesPoint
from backend.services.engine_selector import (
    EngineSelector,
    SEASONAL_FRED_CATALOG,
    DIVERSIFIED_ETF_CATALOG,
    LOW_CONFIDENCE_HISTORY_THRESHOLD,
)
from backend.services.forecast_engine import TimesFMForecastEngine


@pytest.fixture
def isolated_timesfm_singleton():
    """See test_forecast_engine.py: TimesFMForecastEngine is a class-level
    singleton, so tests that force a real load must reset it before/after to
    avoid leaking a warm _model into unrelated tests."""
    TimesFMForecastEngine._instance = None
    yield
    TimesFMForecastEngine._instance = None


def _timesfm_weights_available() -> bool:
    try:
        import torch  # noqa: F401
        import timesfm  # noqa: F401
        from huggingface_hub import constants
    except ImportError:
        return False
    cache_dir = Path(constants.HF_HUB_CACHE)
    repo_dir = cache_dir / "models--google--timesfm-2.5-200m-pytorch"
    return repo_dir.exists() and any(repo_dir.iterdir())


def _make_points(n: int, start_value: float = 100.0) -> list[TimeSeriesPoint]:
    return [
        TimeSeriesPoint(timestamp=f"2020-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}", value=start_value + i * 0.3)
        for i in range(n)
    ]


def test_selector_uses_holt_for_individual_equity_with_history():
    """Default path, unchanged: an individual equity with ample history (not in
    any curated catalog) still gets Holt, exactly as get_forecast_engine() did
    before this feature — see EngineSelector docstring, benchmark found no
    category-wide reason to change this default."""
    points = _make_points(300)
    res = EngineSelector.select(points, series_id="AAPL", series_type="equity", horizon=10)

    assert res.model_name == "damped-holt-mle"
    assert res.is_fallback is False
    assert "Holt (default)" in res.engine_selection_reason


def test_selector_falls_back_to_holt_for_short_history_with_explicit_reason():
    """The benchmark (scripts/benchmark_real_data.py) found NO history-length
    window (30/60/90 days) where TimesFM beat Holt in >=50% of cold-start
    tickers — the initial hypothesis that short history favors TimesFM did NOT
    hold. So short history stays on Holt, with the reason naming the real risk
    (an unreliable MLE fit, not an engine swap) instead of silently using the
    same default reason as ample-history series."""
    points = _make_points(LOW_CONFIDENCE_HISTORY_THRESHOLD - 10)
    res = EngineSelector.select(points, series_id="NEWCO", series_type="equity", horizon=5)

    assert res.model_name == "damped-holt-mle"
    assert "Historia insuficiente" in res.engine_selection_reason
    assert res.fitted_params is not None
    assert res.fitted_params.get("low_confidence") == 1.0


def test_selector_uses_holt_for_diversified_etf_despite_initial_hypothesis():
    """The initial hypothesis was that diversified index/ETF baskets would favor
    TimesFM. The real walk-forward benchmark showed TimesFM winning 0/4 ETFs
    (SPY, QQQ, XLE, XLK) — so this category stays on Holt, and the reason says
    so explicitly rather than implying TimesFM was even considered a good fit."""
    assert "SPY" in DIVERSIFIED_ETF_CATALOG
    points = _make_points(300)
    res = EngineSelector.select(points, series_id="SPY", series_type="equity", horizon=30)

    assert res.model_name == "damped-holt-mle"
    assert "no le ganó a Holt" in res.engine_selection_reason


def test_selector_falls_back_gracefully_when_timesfm_unavailable(monkeypatch, isolated_timesfm_singleton):
    """A seasonal FRED series should route to TimesFM per the benchmark — but
    with USE_REAL_TIMESFM=false (or weights unavailable), it must fall back to
    Holt with a reason that says so explicitly, never fail or silently claim
    TimesFM was used."""
    assert "IPG2211A2N" in SEASONAL_FRED_CATALOG
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", False)

    points = _make_points(300)
    res = EngineSelector.select(points, series_id="IPG2211A2N", series_type="macro", horizon=6, freq="M")

    assert res.model_name == "damped-holt-mle"
    assert res.is_fallback is False  # Holt itself succeeded; EngineSelector chose it deliberately
    assert "USE_REAL_TIMESFM=false" in res.engine_selection_reason


@pytest.mark.skipif(
    not _timesfm_weights_available(),
    reason=(
        "Real TimesFM 2.5 (200M) weights are not cached locally in this environment. "
        "This test intentionally exercises the real model (the whole point is verifying "
        "EngineSelector actually routes to it for this catalog), not a mock of it. "
        "Run `python scripts/download_and_benchmark_timesfm.py --yes` locally first."
    ),
)
def test_selector_uses_timesfm_for_seasonal_fred_series(monkeypatch, isolated_timesfm_singleton):
    """Confirmed by the real benchmark: TimesFM won 4/4 seasonal FRED series
    (IPG2211A2N, RSAFSNA, HOUSTNSA, MRTSSM4451USN) — see EngineSelector's
    docstring for the MASE numbers. With TimesFM actually available, this
    category must route to it, not to the Holt default."""
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", True)
    points = _make_points(300)
    res = EngineSelector.select(points, series_id="IPG2211A2N", series_type="macro", horizon=6, freq="M")

    assert "timesfm" in res.model_name.lower()
    assert res.is_fallback is False
    assert "TimesFM seleccionado" in res.engine_selection_reason
