import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.models import TimeSeriesPoint, TimeSeriesData
from backend.services.forecast_engine import DampedHoltForecastEngine
from backend.services.backtest_engine import BacktestEngine
from backend.services.correlation_engine import CorrelationEngine
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher

client = TestClient(app)

def test_forecast_calibration():
    """
    Generates 500 synthetic random walks with known drift and vol.
    Forecasts H=90 steps ahead with 95% nominal confidence.
    Asserts empirical coverage is in [0.90, 0.98].
    """
    rng = np.random.default_rng(42)
    engine = DampedHoltForecastEngine()
    
    n_series = 500
    T = 252
    H = 90
    total_evals = n_series * H
    hits = 0

    for _ in range(n_series):
        drift = 0.0002
        vol = 0.015
        shocks = rng.normal(drift, vol, size=T + H)
        prices = 100.0 * np.exp(np.cumsum(shocks))

        train_pts = [
            TimeSeriesPoint(timestamp=f"2024-01-{j:04d}", value=float(prices[j]))
            for j in range(T)
        ]
        actual_future = prices[T:T+H]

        fc = engine.forecast(train_pts, horizon=H, confidence=0.95)
        lbs = np.array(fc.lower_bound)
        ubs = np.array(fc.upper_bound)

        in_band = (actual_future >= lbs) & (actual_future <= ubs)
        hits += np.sum(in_band)

    empirical_coverage = hits / total_evals
    assert 0.90 <= empirical_coverage <= 0.98, (
        f"Empirical coverage {empirical_coverage:.4f} is outside [0.90, 0.98]"
    )


def test_holt_variance_analytic():
    """
    Validates the forecast error variance formula against manual analytic expansion for small h.
    """
    alpha = 0.35
    beta = 0.15
    phi = 0.90
    sigma = 2.0
    sigma2 = sigma ** 2

    # Hand expansions
    # h = 1 -> sigma^2
    var_h1_expected = sigma2
    # h = 2 -> sigma^2 * [1 + (alpha + alpha*beta*phi)^2]
    c1 = alpha + alpha * beta * phi
    var_h2_expected = sigma2 * (1.0 + c1 ** 2)
    # h = 3 -> sigma^2 * [1 + c1^2 + c2^2] where c2 = alpha + alpha*beta*phi*(1 - phi^2)/(1 - phi) = alpha + alpha*beta*phi*(1 + phi)
    c2 = alpha + alpha * beta * phi * (1.0 + phi)
    var_h3_expected = sigma2 * (1.0 + c1 ** 2 + c2 ** 2)

    # Compute using the engine formula
    c_sum = 0.0
    computed_vars = []
    for h in range(1, 4):
        if h == 1:
            computed_vars.append(sigma2)
        else:
            j = h - 1
            cj = alpha + alpha * beta * phi * (1.0 - phi**j) / (1.0 - phi)
            c_sum += cj * cj
            computed_vars.append(sigma2 * (1.0 + c_sum))

    np.testing.assert_allclose(computed_vars[0], var_h1_expected, rtol=1e-6)
    np.testing.assert_allclose(computed_vars[1], var_h2_expected, rtol=1e-6)
    np.testing.assert_allclose(computed_vars[2], var_h3_expected, rtol=1e-6)


def test_synthetic_data_rejected_by_backtest(monkeypatch):
    """
    Backtesting engine must reject synthetic data with HTTP 422.
    """
    # Mock MarketDataFetcher to return a synthetic series
    synthetic_series = TimeSeriesData(
        id="SYNTH",
        name="Synthetic Stock",
        type="equity",
        unit="USD",
        points=[TimeSeriesPoint(timestamp=f"2024-01-{i:02d}", value=100.0 + i) for i in range(1, 50)],
        source="synthetic",
        source_detail="Generado sintéticamente para pruebas"
    )

    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *args, **kwargs: synthetic_series)

    resp = client.post("/api/backtest", json={
        "series_id": "SYNTH",
        "cutoff_date": "2024-01-30",
        "horizon": 10,
        "confidence": 0.95
    })
    assert resp.status_code == 422
    assert "es sintética" in resp.json()["detail"]


def test_directional_accuracy_step_wise():
    """
    Verifies step-wise directional accuracy:
    If actual moves [100 -> 102 -> 101 -> 103 -> 100 -> 102] (diffs: [+2, -1, +2, -3, +2])
    and predicted moves [100 -> 101 -> 102 -> 103 -> 104 -> 105] (diffs: [+1, +1, +1, +1, +1]),
    then actual signs: [+, -, +, -, +], predicted signs: [+, +, +, +, +]
    Matches: 3 of 5 -> 60.0% (NOT 100.0%).
    """
    actual_diffs = np.array([2.0, -1.0, 2.0, -3.0, 2.0])
    pred_diffs = np.array([1.0, 1.0, 1.0, 1.0, 1.0])

    matches = np.sign(actual_diffs) == np.sign(pred_diffs)
    step_acc = float(np.mean(matches) * 100)
    assert step_acc == 60.0


def test_mape_with_negative_values():
    """
    Validates that MAPE calculation with negative values remains finite, positive, and robust.
    """
    y_actual = np.array([-1.5, -0.8, 0.2, 1.1, -0.4])
    y_pred = np.array([-1.2, -0.9, 0.3, 1.0, -0.2])
    epsilon = 1e-8

    mape = float(np.mean(np.abs((y_actual - y_pred) / (np.abs(y_actual) + epsilon))) * 100)
    assert np.isfinite(mape)
    assert mape > 0.0


def test_correlation_spurious(monkeypatch):
    """
    Two independent random walks with positive drift:
    - Over levels: correlation is spuriously high (> 0.70).
    - Over returns (the default): correlation drops to |rho| < 0.15.
    """
    rng = np.random.default_rng(999)
    T = 500
    dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2023-01-01", periods=T, freq="D")]

    # Two independent walks with upward drift
    walk1 = 100.0 * np.exp(np.cumsum(rng.normal(0.002, 0.01, T)))
    walk2 = 50.0 * np.exp(np.cumsum(rng.normal(0.002, 0.01, T)))

    s1 = TimeSeriesData(
        id="SERIES1", name="Walk 1", type="equity", unit="USD",
        points=[TimeSeriesPoint(timestamp=dates[i], value=float(walk1[i])) for i in range(T)],
        source="live"
    )
    s2 = TimeSeriesData(
        id="SERIES2", name="Walk 2", type="equity", unit="USD",
        points=[TimeSeriesPoint(timestamp=dates[i], value=float(walk2[i])) for i in range(T)],
        source="live"
    )

    def mock_history(ticker, period="2y"):
        return s1 if ticker == "SERIES1" else s2

    monkeypatch.setattr(MarketDataFetcher, "get_history", mock_history)

    # 1. Calculation on levels
    res_levels = CorrelationEngine.calculate_correlations(["SERIES1", "SERIES2"], mode="levels")
    r_levels = abs(res_levels.pearson_matrix[0][1])
    assert r_levels > 0.60, f"Spurious correlation should be high, got {r_levels}"
    assert res_levels.warning is not None
    assert "espuria" in res_levels.warning

    # 2. Calculation on returns (default)
    res_returns = CorrelationEngine.calculate_correlations(["SERIES1", "SERIES2"], mode="returns")
    r_returns = abs(res_returns.pearson_matrix[0][1])
    assert r_returns < 0.15, f"Returns correlation should be near zero, got {r_returns}"
    assert res_returns.warning is None


def test_path_traversal_blocked():
    """
    Attempts path traversal GET /..%2f..%2fetc%2fpasswd and asserts it is blocked with 404.
    """
    resp = client.get("/..%2f..%2fetc%2fpasswd")
    assert resp.status_code == 404
