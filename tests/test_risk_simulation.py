"""
Risk simulation: a new seed per run (shown, reproducible) and the historical
trend removed by default (fix/risk-simulation). Synthetic returns with a
known drift; no network.
"""
import numpy as np
import pytest

from backend.schemas.models import PortfolioRiskRequest
from backend.services.risk_engine import RiskEngine

TICKERS = ["AAA", "BBB"]
DAILY_DRIFT = 0.002   # ~ +50% a year in log terms: a strong rally


@pytest.fixture
def rally(monkeypatch):
    rng = np.random.default_rng(7)
    returns = DAILY_DRIFT + rng.normal(0, 0.02, size=(500, 2))
    monkeypatch.setattr(RiskEngine, "align_historical_returns", staticmethod(lambda t, period="2y": (returns, TICKERS)))
    return returns


def _req(**kw):
    base = dict(tickers=TICKERS, weights={"AAA": 0.5, "BBB": 0.5}, horizon_days=90, n_simulations=5000)
    base.update(kw)
    return PortfolioRiskRequest(**base)


def test_each_run_gets_a_new_seed_and_reports_it(rally):
    a = RiskEngine.evaluate_risk(_req())
    b = RiskEngine.evaluate_risk(_req())
    assert a.seed_used != b.seed_used
    assert a.metrics["95%"].var_pct != b.metrics["95%"].var_pct


def test_the_same_seed_reproduces_the_run(rally):
    a = RiskEngine.evaluate_risk(_req(seed=123456))
    b = RiskEngine.evaluate_risk(_req(seed=a.seed_used))
    assert b.seed_used == 123456
    assert a.metrics == b.metrics and a.prob_loss_10pct == b.prob_loss_10pct


def test_centered_is_the_default_and_removes_the_trend(rally):
    default = RiskEngine.evaluate_risk(_req(seed=1))
    assert default.drift_used == "centered"
    hist = RiskEngine.evaluate_risk(_req(seed=1, drift="historical"))
    assert hist.drift_used == "historical"
    # Same seed, same shocks: only the trend differs, and keeping it shrinks the losses.
    assert default.metrics["95%"].var_pct > hist.metrics["95%"].var_pct
    assert default.prob_loss_10pct > hist.prob_loss_10pct
    # What "centered" removes is reported, whichever option ran.
    expected = float(rally.mean(axis=0).mean() * 252)
    assert default.historical_drift_annual == pytest.approx(expected, abs=1e-4)
    assert hist.historical_drift_annual == pytest.approx(expected, abs=1e-4)


@pytest.mark.parametrize("method", ["bootstrap", "student_t", "gaussian"])
def test_centered_simulation_has_no_trend(rally, method):
    res = RiskEngine.evaluate_risk(_req(seed=5, method=method, drift="centered"))
    # Median simulated return near 0 (not the +~18% the rally would give over 90 days).
    assert abs(res.histogram.median) < 0.03
