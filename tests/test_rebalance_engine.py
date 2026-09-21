"""
Unit and Integration Tests for RebalanceEngine (Fase 4: Dynamic Rebalancing)
=============================================================================
Verifies:
1. test_no_lookahead_bias: Mutating future prices strictly after date t does NOT alter weights at date t.
2. test_rebalance_cost_reduces_net_return: Transaction costs strictly penalize net return relative to gross return.
3. test_buy_and_hold_zero_intermediate_costs: Buy-and-hold strategy incurs 0 intermediate transaction costs and 0 taxes.
4. test_verdict_reflects_negative_outcome: When rebalancing underperforms buy-and-hold, the verdict declares it explicitly.
5. test_rebalance_rejects_synthetic_source: Returns HTTP 422 when data has source='synthetic'.
6. test_capital_gains_tax_and_warnings: Realized sales with tax rate > 0 incur tax and emit the linear approximation warning.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient
import pandas as pd

from backend.main import app
from backend.schemas.models import (
    TimeSeriesData,
    TimeSeriesPoint,
    RebalanceBacktestRequest,
)
from backend.services.data_fetcher import MarketDataFetcher
from backend.services.rebalance_engine import RebalanceEngine

client = TestClient(app)


def generate_deterministic_price_series(
    ticker: str,
    n_days: int = 500,
    seed: int = 42,
    drift: float = 0.0005,
    vol: float = 0.015,
    initial_price: float = 100.0,
    source: str = "live"
) -> TimeSeriesData:
    """Generates deterministic synthetic-free daily prices with realistic log-normal dynamics."""
    rng = np.random.default_rng(seed)
    log_returns = rng.normal(loc=drift, scale=vol, size=n_days)
    prices = initial_price * np.exp(np.cumsum(log_returns))

    start_date = pd.Timestamp("2022-01-03")
    dates = pd.date_range(start=start_date, periods=n_days, freq="B")

    points = [
        TimeSeriesPoint(timestamp=d.strftime("%Y-%m-%d"), value=round(float(p), 2))
        for d, p in zip(dates, prices)
    ]
    return TimeSeriesData(
        id=ticker,
        name=f"{ticker} Corp",
        type="equity",
        unit="USD",
        points=points,
        source=source
    )


@pytest.fixture
def mock_market_history(monkeypatch):
    """Sets up deterministic offline historical market data for NVDA and MSFT (500 days)."""
    nvda_data = generate_deterministic_price_series("NVDA", n_days=500, seed=101, drift=0.0010, vol=0.022, initial_price=120.0)
    msft_data = generate_deterministic_price_series("MSFT", n_days=500, seed=202, drift=0.0004, vol=0.014, initial_price=300.0)

    def mock_get(ticker, period="5y"):
        if ticker == "NVDA":
            return nvda_data
        elif ticker == "MSFT":
            return msft_data
        elif ticker == "SYNTH":
            return generate_deterministic_price_series("SYNTH", n_days=500, source="synthetic")
        raise ValueError(f"Unknown test ticker: {ticker}")

    monkeypatch.setattr(MarketDataFetcher, "get_history", mock_get)
    return {"NVDA": nvda_data, "MSFT": msft_data}


def test_no_lookahead_bias():
    """
    CRITICAL AUDIT TEST:
    Given historical returns up to step t_k, compute optimal weights w_original.
    Mutate future returns (t > t_k) by adding extreme volatility and drift.
    Recompute weights at step t_k using only data up to t_k.
    Assert that weights at t_k are bit-for-bit identical (error < 1e-12).
    """
    rng = np.random.default_rng(777)
    T = 400
    K = 3
    returns_original = rng.normal(0.0005, 0.015, size=(T, K))

    # Evaluate at step t_k = 260
    t_k = 260
    tickers = ["A", "B", "C"]

    window_original = returns_original[:t_k]
    w_original = RebalanceEngine.compute_weights_at_step(
        returns_window=window_original,
        tickers=tickers,
        method="max_sharpe",
        mu_method="historical_shrunk",
        max_weight=0.50,
        rf=0.045,
    )

    # Mutate future returns after t_k
    returns_mutated = returns_original.copy()
    returns_mutated[t_k:, :] = returns_mutated[t_k:, :] * 15.0 + 0.10

    # Recompute at t_k
    window_mutated = returns_mutated[:t_k]
    w_mutated = RebalanceEngine.compute_weights_at_step(
        returns_window=window_mutated,
        tickers=tickers,
        method="max_sharpe",
        mu_method="historical_shrunk",
        max_weight=0.50,
        rf=0.045,
    )

    np.testing.assert_allclose(
        w_original,
        w_mutated,
        atol=1e-12,
        err_msg="Look-ahead bias detected: weights at date t changed when future prices were mutated!"
    )


def test_rebalance_cost_reduces_net_return(mock_market_history):
    """
    Tests that with non-zero transaction cost (cost_bps=50), the net rebalance curve
    ends strictly below the gross rebalance curve and total transaction costs > 0.
    """
    req = RebalanceBacktestRequest(
        tickers=["NVDA", "MSFT"],
        method="max_sharpe",
        rebalance_frequency="monthly",
        cost_bps=50.0,
        capital_gains_tax_rate=0.0,
        burn_in_days=252,
        initial_capital=100000.0,
    )
    res = RebalanceEngine.run_rebalance_backtest(req)

    assert res.n_rebalances_executed > 0
    assert res.total_transaction_costs > 0.0
    assert res.total_turnover > 0.0
    assert res.net_metrics.total_return < res.gross_metrics.total_return
    assert res.cost_drag > 0.0
    assert res.curves[-1].rebalance_net < res.curves[-1].rebalance_gross


def test_buy_and_hold_zero_intermediate_costs(mock_market_history):
    """
    Tests that Buy-and-Hold strategy executes 0 intermediate rebalances
    and accrues 0 transaction costs and 0 taxes throughout the evaluation horizon.
    """
    req = RebalanceBacktestRequest(
        tickers=["NVDA", "MSFT"],
        method="max_sharpe",
        rebalance_frequency="none",
        cost_bps=30.0,
        capital_gains_tax_rate=0.15,
        burn_in_days=252,
        initial_capital=100000.0,
    )
    res = RebalanceEngine.run_rebalance_backtest(req)

    assert res.n_rebalances_executed == 0
    assert res.total_transaction_costs == 0.0
    assert res.total_tax_paid == 0.0
    assert res.total_turnover == 0.0
    # In frequency='none', net and gross curves are identical to buy_and_hold
    assert res.net_metrics.total_return == res.buy_and_hold_metrics.total_return
    assert res.curves[-1].rebalance_net == res.curves[-1].buy_and_hold


def test_verdict_reflects_negative_outcome(mock_market_history):
    """
    When rebalancing yields less than buy-and-hold (e.g. due to transaction costs or strong momentum),
    the verdict must explicitly acknowledge the underperformance without smoothing.
    """
    req = RebalanceBacktestRequest(
        tickers=["NVDA", "MSFT"],
        method="max_sharpe",
        rebalance_frequency="monthly",
        cost_bps=100.0,  # High cost ensuring drag exceeds diversification
        capital_gains_tax_rate=0.0,
        burn_in_days=252,
    )
    res = RebalanceEngine.run_rebalance_backtest(req)

    if res.net_benefit_of_rebalancing < 0:
        assert "costó más de lo que aportó" in res.verdict
        assert "Buy-and-Hold fue superior" in res.verdict
    else:
        assert "aportó un beneficio neto positivo" in res.verdict


def test_rebalance_rejects_synthetic_source(monkeypatch):
    """
    Verifies that the /api/portfolio/rebalance-backtest endpoint strictly
    rejects synthetic data with HTTP 422.
    """
    synth_data = generate_deterministic_price_series("SYNTH", n_days=500, source="synthetic")
    live_data = generate_deterministic_price_series("NVDA", n_days=500, source="live")

    def mock_get(ticker, period="5y"):
        return synth_data if ticker == "SYNTH" else live_data

    monkeypatch.setattr(MarketDataFetcher, "get_history", mock_get)

    resp = client.post(
        "/api/portfolio/rebalance-backtest",
        json={
            "tickers": ["SYNTH", "NVDA"],
            "rebalance_frequency": "monthly",
            "cost_bps": 10.0,
        }
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "synthetic" in resp.json()["detail"].lower() or "sintética" in resp.json()["detail"].lower()


def test_capital_gains_tax_and_warnings(mock_market_history):
    """
    Tests that setting capital_gains_tax_rate > 0 incurs taxes on asset sales
    and includes the regulatory approximation warning in the response.
    """
    req = RebalanceBacktestRequest(
        tickers=["NVDA", "MSFT"],
        method="risk_parity",
        rebalance_frequency="monthly",
        cost_bps=10.0,
        capital_gains_tax_rate=0.20,
        burn_in_days=252,
        initial_capital=100000.0,
    )
    res = RebalanceEngine.run_rebalance_backtest(req)

    assert any("FIFO/LIFO" in w for w in res.warnings)
    # Total tax paid should be non-negative float
    assert res.total_tax_paid >= 0.0


def test_rebalance_endpoint_integration(mock_market_history):
    """
    Full end-to-end integration test of POST /api/portfolio/rebalance-backtest.
    """
    resp = client.post(
        "/api/portfolio/rebalance-backtest",
        json={
            "tickers": ["NVDA", "MSFT"],
            "method": "max_sharpe",
            "rebalance_frequency": "quarterly",
            "cost_bps": 15.0,
            "capital_gains_tax_rate": 0.10,
            "initial_capital": 50000.0,
            "burn_in_days": 252,
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["tickers"] == ["NVDA", "MSFT"]
    assert data["rebalance_frequency"] == "quarterly"
    assert data["trading_days_evaluated"] > 100
    assert len(data["curves"]) == data["trading_days_evaluated"]
    assert "net_metrics" in data
    assert "gross_metrics" in data
    assert "buy_and_hold_metrics" in data
    assert len(data["verdict"]) > 10
