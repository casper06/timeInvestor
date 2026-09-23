import builtins
import pytest
from pathlib import Path
from backend.schemas.models import TimeSeriesPoint
from backend.services.forecast_engine import StatisticalMockForecastEngine, TimesFMForecastEngine


def test_default_config_has_timesfm_enabled():
    """
    Settings.USE_REAL_TIMESFM's CODE default is True as of EngineSelector: the
    selector itself already restricts real TimesFM usage to a handful of
    benchmark-confirmed categories (seasonal FRED series), so there's no
    downside to leaving this on by default — it doesn't trigger broad heavy
    model usage, only enables it where the benchmark says it wins.

    Settings' fields are class attributes evaluated once at class-definition
    time (os.getenv(...) runs when backend.config is first imported, not
    inside __init__), so instantiating a fresh Settings() later can't
    re-observe a changed environment — this test reads the source directly
    for the literal default string passed to os.getenv, which is the only
    reliable way to assert the CODE default independent of whatever a local
    .env happens to set at import time (this repo's own .env sets it to
    false, overriding the default for actual runtime behavior — expected).
    """
    import inspect
    from backend.config import Settings

    source = inspect.getsource(Settings)
    assert 'os.getenv("USE_REAL_TIMESFM", "true")' in source, (
        "Settings.USE_REAL_TIMESFM's default argument to os.getenv must be "
        '"true" — found a different default in backend/config.py'
    )

def test_statistical_mock_forecast():
    engine = StatisticalMockForecastEngine()
    
    # Generate simple historical series
    points = [
        TimeSeriesPoint(timestamp=f"2024-01-{i:02d}", value=100.0 + i * 1.5)
        for i in range(1, 20)
    ]
    
    horizon = 10
    confidence = 0.95
    resp = engine.forecast(points, horizon=horizon, confidence=confidence, freq="D")
    
    # Verify TimesFM schema conformance
    assert len(resp.timestamps) == horizon
    assert len(resp.values) == horizon
    assert len(resp.lower_bound) == horizon
    assert len(resp.upper_bound) == horizon
    assert resp.model_name == "damped-holt-mle"
    assert resp.is_fallback is False

    # Lower bound must be <= forecast value <= upper bound
    for v, lb, ub in zip(resp.values, resp.lower_bound, resp.upper_bound):
        assert lb <= v, f"Lower bound {lb} must be <= value {v}"
        assert v <= ub, f"Value {v} must be <= upper bound {ub}"

@pytest.fixture
def isolated_timesfm_singleton():
    """
    TimesFMForecastEngine caches itself as a class-level singleton (__new__ returns
    a shared _instance across calls), so a test that forces a real model load would
    otherwise leak a warm _model into every later test expecting a fresh one.
    Reset the singleton before and after each test that touches it.
    """
    TimesFMForecastEngine._instance = None
    yield
    TimesFMForecastEngine._instance = None


def _timesfm_weights_available() -> bool:
    """
    True only if torch/timesfm are importable AND the real checkpoint is already
    cached locally — i.e. loading it will not attempt a network download.
    """
    try:
        import torch  # noqa: F401
        import timesfm  # noqa: F401
        from huggingface_hub import constants
    except ImportError:
        return False

    cache_dir = Path(constants.HF_HUB_CACHE)
    repo_dir = cache_dir / "models--google--timesfm-2.5-200m-pytorch"
    return repo_dir.exists() and any(repo_dir.iterdir())


def test_timesfm_adapter_fallback(isolated_timesfm_singleton, monkeypatch):
    """USE_REAL_TIMESFM=false must never even attempt to load the real model —
    forced explicitly here (independent of Settings' default, which is true as
    of this project's EngineSelector work) so this test can't accidentally pass
    or fail based on whichever real default happens to be configured."""
    from backend.config import settings
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", False)

    engine = TimesFMForecastEngine()
    points = [
        TimeSeriesPoint(timestamp="2024-01-01", value=50.0),
        TimeSeriesPoint(timestamp="2024-01-02", value=52.0),
        TimeSeriesPoint(timestamp="2024-01-03", value=51.5),
    ]
    resp = engine.forecast(points, horizon=5)
    assert len(resp.values) == 5
    assert "damped-holt-mle" in resp.model_name
    assert resp.is_fallback is True


def test_light_image_graceful_fallback_no_repeated_errors(isolated_timesfm_singleton, monkeypatch):
    """
    Simulates the default (light) Docker image: torch/timesfm genuinely absent
    (blocks the import itself, not just missing weights) — this is the exact
    scenario a EngineSelector-routed seasonal FRED series hits with
    USE_REAL_TIMESFM=true but no requirements-timesfm.txt installed.

    _load_model() must run AT MOST ONCE across repeated forecast() calls on the
    same (singleton) engine instance — the failed-to-load result is cached at
    the process level via self._model staying None, not re-attempted on every
    request. Re-attempting every time would mean paying the failed-import cost
    (and re-logging the same warning) on every single forecast for these series.
    """
    from backend.config import settings
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", True)

    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "timesfm":
            raise ImportError(f"No module named {name!r} (simulated light image)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)

    load_attempts = {"n": 0}
    original_load_model = TimesFMForecastEngine._load_model

    def counting_load_model(self):
        load_attempts["n"] += 1
        original_load_model(self)

    monkeypatch.setattr(TimesFMForecastEngine, "_load_model", counting_load_model)

    points = [
        TimeSeriesPoint(timestamp=f"2020-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}", value=100.0 + i * 0.3)
        for i in range(300)
    ]

    for _ in range(3):
        engine = TimesFMForecastEngine()
        resp = engine.forecast(points, horizon=6, confidence=0.95, freq="M")
        assert resp.is_fallback is True
        assert "damped-holt-mle" in resp.model_name

    assert load_attempts["n"] == 1, (
        f"_load_model was invoked {load_attempts['n']} times across 3 forecasts — "
        "the failed load must be cached after the first attempt, not retried per request"
    )


@pytest.mark.skipif(
    not _timesfm_weights_available(),
    reason=(
        "Real TimesFM 2.5 (200M) weights (~900MB) are not cached locally in this "
        "environment. This test intentionally runs the REAL model rather than a "
        "mock of it — the whole point is verifying the actual from_pretrained() + "
        "compile() + forecast() path against the real checkpoint, which a mock "
        "can't validate. CI environments without the weights pre-warmed in cache "
        "(and without network egress to Hugging Face) will skip this test rather "
        "than fail or silently pass on a mocked substitute; run it locally after "
        "`python scripts/download_and_benchmark_timesfm.py --yes` to exercise it."
    ),
)
def test_timesfm_real_loads_when_weights_present(isolated_timesfm_singleton):
    """
    With the real checkpoint cached, TimesFMForecastEngine must actually load and
    run Google TimesFM 2.5 (200M) — not silently stay on the Holt fallback — and
    report is_fallback=False with a model_name that names the real engine.
    """
    engine = TimesFMForecastEngine()
    engine._load_model()
    assert engine._model is not None, "TimesFM real weights are cached but failed to load"

    points = [
        TimeSeriesPoint(timestamp=f"2024-01-{i:02d}" if i <= 28 else f"2024-02-{i-28:02d}", value=100.0 + i * 0.5)
        for i in range(1, 40)
    ]
    resp = engine.forecast(points, horizon=10, confidence=0.95)

    assert resp.is_fallback is False
    assert "timesfm" in resp.model_name.lower()
    assert len(resp.values) == 10
    assert len(resp.lower_bound) == 10
    assert len(resp.upper_bound) == 10
    for v, lb, ub in zip(resp.values, resp.lower_bound, resp.upper_bound):
        assert lb <= ub, f"Lower bound {lb} must be <= upper bound {ub}"
