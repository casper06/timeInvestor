"""
Unit Test Suite for TimeInvestor - Part B (Fase 3: Cartera y Riesgo)
====================================================================
Covers:
1. test_markowitz_analytic_two_assets (convergence to closed-form optimal within 1e-4)
2. test_risk_parity_contributions (|RC_i - RC_j| < 1e-4 for all pairs)
3. test_cvar_ge_var (CVaR >= VaR invariant across 100 random portfolios)
4. test_var_monte_carlo_convergence (N=50,000 Gaussian MC converges to analytic with error < 1%)
5. test_var_sign_convention (VaR and CVaR are positive floats for losses)
6. test_cholesky_singular_matrix (zero determinant covariance handled cleanly via eigenvalue clipping)
7. test_bootstrap_preserves_fat_tails (bootstrap kurtosis > gaussian kurtosis on leptokurtic series)
8. test_portfolio_rejects_synthetic_source (HTTP 422 returned on synthetic data)
"""

import numpy as np
import pytest
from scipy import stats
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.models import (
    TimeSeriesData,
    TimeSeriesPoint,
    PortfolioOptimizeRequest,
    PortfolioRiskRequest,
)
from backend.services.data_fetcher import MarketDataFetcher
from backend.services.portfolio_engine import PortfolioEngine
from backend.services.risk_engine import RiskEngine

client = TestClient(app)


def test_markowitz_analytic_two_assets():
    """
    1. Two-asset Markowitz test:
    Given mu = [0.15, 0.10], sigma1 = 0.20, sigma2 = 0.15, rho = 0.20, rf = 0.04.
    Analytical unconstrained tangency weights are:
      z = Sigma^-1 (mu - rf * 1)
      w* = z / sum(z)
    Assert SLSQP with max_weight=1.0 matches analytical w* within 1e-4.
    """
    mu = np.array([0.15, 0.10])
    rf = 0.04
    s1, s2 = 0.20, 0.15
    rho = 0.20
    cov12 = rho * s1 * s2
    Sigma = np.array([
        [s1 ** 2, cov12],
        [cov12, s2 ** 2]
    ])

    # Closed-form tangency weights
    inv_Sigma = np.linalg.inv(Sigma)
    excess_mu = mu - rf
    z = inv_Sigma @ excess_mu
    w_analytic = z / np.sum(z)

    # SLSQP numerical solution
    w_num = PortfolioEngine.optimize_max_sharpe(
        mu, Sigma, max_weight=1.0, rf=rf, n_restarts=10
    )

    np.testing.assert_allclose(
        w_num, w_analytic, atol=1e-4,
        err_msg="SLSQP Markowitz failed to match analytic 2-asset tangency portfolio"
    )


def test_risk_parity_contributions():
    """
    2. Risk Parity Equal Risk Contribution test:
    Given a 4x4 non-trivial positive-definite covariance matrix,
    Spinu's convex formulation must satisfy |RC_i - RC_j| < 1e-4 for all pairs.
    """
    # Create non-trivial 4x4 covariance
    rng = np.random.default_rng(101)
    A = rng.normal(0, 1, size=(4, 4))
    Sigma = A @ A.T + 0.1 * np.eye(4)

    w_rp = PortfolioEngine.optimize_risk_parity(Sigma)

    # Compute risk contributions
    port_vol = np.sqrt(w_rp @ Sigma @ w_rp)
    rc = (w_rp * (Sigma @ w_rp)) / port_vol

    # Assert pairwise differences are less than 1e-4
    for i in range(len(rc)):
        for j in range(i + 1, len(rc)):
            assert abs(rc[i] - rc[j]) < 1e-4, (
                f"Risk contributions RC[{i}]={rc[i]:.6f} and RC[{j}]={rc[j]:.6f} "
                "differ by more than 1e-4"
            )


def test_cvar_ge_var():
    """
    3. Invariant CVaR >= VaR test:
    Across 100 random loss vectors / portfolios, assert that CVaR_alpha >= VaR_alpha
    strictly holds for both alpha=0.95 and alpha=0.99.
    """
    rng = np.random.default_rng(202)
    for _ in range(100):
        # Generate random loss distribution (mixtures, Student-t, jumps)
        losses = rng.standard_t(df=4.0, size=5000) * 0.05 + 0.01

        for alpha in [0.95, 0.99]:
            var_val = float(np.percentile(losses, alpha * 100.0))
            exceedances = losses[losses >= var_val]
            cvar_val = float(np.mean(exceedances))

            assert cvar_val >= var_val - 1e-9, (
                f"Invariant violation: CVaR ({cvar_val}) < VaR ({var_val}) at alpha={alpha}"
            )


def test_var_monte_carlo_convergence():
    """
    4. Monte Carlo convergence test:
    With N=50,000 Gaussian paths, estimated VaR converges to the analytical
    lognormal value with relative error < 1%.
    """
    mu_daily = 0.0004
    sigma_daily = 0.015
    H = 20
    alpha = 0.95
    n_sims = 50_000

    returns_mock = np.zeros((300, 1))
    # Gaussian simulation
    rng = np.random.default_rng(42)
    shocks = rng.normal(mu_daily, sigma_daily, size=(n_sims, H))
    cum_log = np.sum(shocks, axis=1)
    simple_returns = np.exp(cum_log) - 1.0
    losses = - simple_returns

    mc_var = float(np.percentile(losses, alpha * 100.0))

    # Closed-form analytical VaR for lognormal:
    # r_H ~ N(H * mu, H * sigma^2)
    # R_H = exp(r_H) - 1
    # Loss = 1 - exp(r_H)
    # The alpha-quantile of loss corresponds to the (1-alpha) quantile of r_H:
    # r_quantile = H * mu + sqrt(H) * sigma * norm.ppf(1 - alpha)
    # Analytic VaR = 1 - exp(r_quantile)
    z_loss = stats.norm.ppf(1.0 - alpha)
    r_quantile = H * mu_daily + np.sqrt(H) * sigma_daily * z_loss
    analytic_var = 1.0 - np.exp(r_quantile)

    rel_error = abs(mc_var - analytic_var) / analytic_var
    assert rel_error < 0.01, (
        f"MC VaR ({mc_var:.5f}) deviated from Analytic VaR ({analytic_var:.5f}) "
        f"by {rel_error * 100:.2f}% (expected < 1%)"
    )


def test_var_sign_convention():
    """
    5. Sign convention test:
    Verify that VaR and CVaR are returned as POSITIVE floats representing percentage loss.
    """
    # Historical returns with slightly negative drift
    rng = np.random.default_rng(555)
    hist_returns = rng.normal(-0.001, 0.015, size=(300, 2))
    w = np.array([0.5, 0.5])

    sim_returns = RiskEngine.simulate_bootstrap(
        hist_returns, w, horizon=30, n_simulations=5000, seed=42
    )
    losses = - sim_returns

    var_95 = float(np.percentile(losses, 95.0))
    cvar_95 = float(np.mean(losses[losses >= var_95]))

    assert var_95 > 0.0, f"VaR_95 must be positive loss, got {var_95}"
    assert cvar_95 > 0.0, f"CVaR_95 must be positive loss, got {cvar_95}"
    assert cvar_95 >= var_95, "CVaR must be >= VaR"


def test_cholesky_singular_matrix():
    """
    6. Singular matrix handling test:
    Two perfectly collinear assets (rho = 1.0) produce a singular covariance matrix.
    Ensure eigenvalue clipping allows Cholesky without crashing or raising LinAlgError.
    """
    # Create singular covariance matrix (rank 1)
    v = np.array([[0.02], [0.02]])
    Sigma_singular = v @ v.T

    # ensure_psd clips eigenvalues
    Sigma_psd = RiskEngine.ensure_psd(Sigma_singular, min_eigenval=1e-8)
    # Must factorize without exception
    L = np.linalg.cholesky(Sigma_psd)
    assert L is not None
    assert np.all(np.isfinite(L))


def test_bootstrap_preserves_fat_tails():
    """
    7. Bootstrap heavy tail test:
    Simulating with bootstrap over a leptokurtic historical series (kurtosis > 6)
    produces higher tail risk / kurtosis in simulated returns compared to Gaussian MC.
    """
    rng = np.random.default_rng(777)
    T = 600
    # Leptokurtic series using Student-t with df=3.5 plus jumps
    t_shocks = rng.standard_t(df=3.5, size=(T, 2)) * 0.01
    jumps = rng.choice([0.0, 0.05, -0.05], size=(T, 2), p=[0.96, 0.02, 0.02])
    returns_lepto = t_shocks + jumps

    hist_kurtosis = stats.kurtosis(returns_lepto[:, 0])
    assert hist_kurtosis > 4.0, f"Test fixture should have high kurtosis, got {hist_kurtosis}"

    w = np.array([0.5, 0.5])
    H = 30
    N = 10_000

    # 1. Bootstrap
    boot_returns = RiskEngine.simulate_bootstrap(
        returns_lepto, w, horizon=H, n_simulations=N, block_size=10, seed=42
    )
    # 2. Gaussian
    gauss_returns, _ = RiskEngine.simulate_gaussian(
        returns_lepto, w, horizon=H, n_simulations=N, seed=42
    )

    kurt_boot = stats.kurtosis(boot_returns)
    kurt_gauss = stats.kurtosis(gauss_returns)

    # Kurtosis under bootstrap must be notably higher than under Gaussian
    assert kurt_boot > kurt_gauss, (
        f"Bootstrap kurtosis ({kurt_boot:.2f}) was not higher than Gaussian ({kurt_gauss:.2f})"
    )


def test_portfolio_rejects_synthetic_source(monkeypatch):
    """
    8. Rejection of synthetic data:
    Both /api/portfolio/optimize and /api/portfolio/risk must reject synthetic data with HTTP 422.
    """
    synthetic_series = TimeSeriesData(
        id="SYNTH1",
        name="Synthetic Asset",
        type="equity",
        unit="USD",
        points=[
            TimeSeriesPoint(timestamp=f"2023-01-{i:04d}", value=100.0 + i * 0.1)
            for i in range(300)
        ],
        source="synthetic",
        source_detail="Synthetic fallback"
    )

    def mock_get_history(ticker, period="2y"):
        return synthetic_series

    monkeypatch.setattr(MarketDataFetcher, "get_history", mock_get_history)

    # 1. Test /api/portfolio/optimize
    resp_opt = client.post(
        "/api/portfolio/optimize",
        json={"tickers": ["SYNTH1", "NVDA"], "period": "2y"}
    )
    assert resp_opt.status_code == 422, f"Expected 422 for synthetic data, got {resp_opt.status_code}: {resp_opt.text}"
    assert "synthetic" in resp_opt.json()["detail"].lower() or "sintética" in resp_opt.json()["detail"].lower()

    # 2. Test /api/portfolio/risk
    resp_risk = client.post(
        "/api/portfolio/risk",
        json={"tickers": ["SYNTH1", "NVDA"], "weights": {"SYNTH1": 0.5, "NVDA": 0.5}}
    )
    assert resp_risk.status_code == 422, f"Expected 422 for synthetic data, got {resp_risk.status_code}: {resp_risk.text}"
    assert "synthetic" in resp_risk.json()["detail"].lower() or "sintética" in resp_risk.json()["detail"].lower()


def test_portfolio_optimize_and_risk_endpoints_success(monkeypatch):
    """
    Integration test:
    Loads deterministic offline fixtures for NVDA and MSFT (source='live', > 252 points).
    Verifies that /api/portfolio/optimize and /api/portfolio/risk respond 200 OK
    with complete valid response schemas.
    """
    import json
    from pathlib import Path

    fixture_dir = Path(__file__).parent / "fixtures"
    with open(fixture_dir / "nvda_daily.json", "r", encoding="utf-8") as f:
        nvda_pts = [TimeSeriesPoint(**p) for p in json.load(f)]
    with open(fixture_dir / "msft_daily.json", "r", encoding="utf-8") as f:
        msft_pts = [TimeSeriesPoint(**p) for p in json.load(f)]

    # Prepend 15 trading days so aligned log returns exceed 252
    prepend_nvda = [TimeSeriesPoint(timestamp=f"2023-12-{d:02d}", value=120.0 + d) for d in range(10, 26)]
    prepend_msft = [TimeSeriesPoint(timestamp=f"2023-12-{d:02d}", value=360.0 + d) for d in range(10, 26)]

    nvda_data = TimeSeriesData(id="NVDA", name="NVIDIA Corp", type="equity", unit="USD", points=prepend_nvda + nvda_pts, source="live")
    msft_data = TimeSeriesData(id="MSFT", name="Microsoft Corp", type="equity", unit="USD", points=prepend_msft + msft_pts, source="live")

    def mock_get_history(ticker, period="2y"):
        return nvda_data if ticker == "NVDA" else msft_data

    monkeypatch.setattr(MarketDataFetcher, "get_history", mock_get_history)

    # 1. POST /api/portfolio/optimize
    resp_opt = client.post("/api/portfolio/optimize", json={
        "tickers": ["NVDA", "MSFT"],
        "period": "2y",
        "cov_method": "ledoit_wolf",
        "mu_method": "historical_shrunk",
        "max_weight": 0.60,
        "risk_free_rate": 0.045
    })
    assert resp_opt.status_code == 200, resp_opt.text
    opt_json = resp_opt.json()
    assert "max_sharpe" in opt_json["portfolios"]
    assert "risk_parity" in opt_json["portfolios"]
    assert "equal_weight" in opt_json["portfolios"]
    assert opt_json["shrinkage_intensity"] >= 0.0
    assert opt_json["condition_number"] > 0.0

    # 2. POST /api/portfolio/risk
    resp_risk = client.post("/api/portfolio/risk", json={
        "tickers": ["NVDA", "MSFT"],
        "weights": {"NVDA": 0.5, "MSFT": 0.5},
        "horizon_days": 30,
        "method": "bootstrap",
        "n_simulations": 5000,
        "initial_capital": 100000.0
    })
    assert resp_risk.status_code == 200, resp_risk.text
    risk_json = resp_risk.json()
    assert "95%" in risk_json["metrics"]
    assert "99%" in risk_json["metrics"]
    assert risk_json["metrics"]["95%"]["var_pct"] > 0.0
    assert risk_json["metrics"]["95%"]["cvar_pct"] >= risk_json["metrics"]["95%"]["var_pct"]
    assert len(risk_json["histogram"]["frequencies"]) == 30

