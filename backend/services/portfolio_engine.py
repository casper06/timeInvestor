"""
TimeInvestor - Portfolio Optimization Engine (Markowitz & Risk Parity)
======================================================================
Implements quantitative portfolio construction:
1. Log-returns alignment and validation (minimum 252 common trading days).
2. Ledoit-Wolf analytical covariance shrinkage (Ledoit & Wolf, 2004).
3. Expected returns (James-Stein shrinkage, equal, or forecast-implied).
4. Maximum Sharpe ratio optimization via SLSQP with multiple Dirichlet random starts.
5. Risk Parity (Equal Risk Contribution) via Spinu (2013) convex logarithmic barrier.
6. Benchmark portfolios (Equal-weight and current thesis weights).
7. Comprehensive performance metrics (volatility, Sharpe, historical Max Drawdown,
   risk contributions, and Choueifaty diversification ratio).
"""

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from backend.schemas.models import (
    PortfolioOptimizeRequest,
    PortfolioOptimizeResponse,
    PortfolioAllocationSummary,
)
from backend.services.data_fetcher import MarketDataFetcher
from backend.services.forecast_engine import DampedHoltForecastEngine

logger = logging.getLogger("TimeInvestor.PortfolioEngine")


class PortfolioEngine:
    """Quantitative engine for portfolio optimization and covariance shrinkage."""

    @staticmethod
    def align_historical_returns(
        tickers: List[str],
        period: str = "2y"
    ) -> Tuple[pd.DataFrame, Dict[str, str]]:
        """
        Fetches historical data for each ticker, validates provenance,
        calculates log-returns, and aligns dates via an inner join.
        Fails if aligned data has fewer than 252 observations.
        """
        returns_dict = {}
        provenance_dict = {}

        for ticker in tickers:
            series = MarketDataFetcher.get_history(ticker, period=period)
            if series.source == "synthetic":
                raise ValueError(
                    f"Ticker '{ticker}' contains synthetic data. "
                    "Portfolio optimization requires live or cached market data."
                )
            provenance_dict[ticker] = series.source

            if len(series.points) < 2:
                raise ValueError(f"Insufficient historical data points for ticker '{ticker}'")

            # Build pandas Series
            dates = [p.timestamp for p in series.points]
            prices = [p.value for p in series.points]
            s = pd.Series(prices, index=pd.to_datetime(dates), name=ticker).sort_index()

            # Remove duplicate timestamps if any
            s = s[~s.index.duplicated(keep="last")]

            # Compute log returns: ln(P_t / P_{t-1})
            log_ret = np.log(s / s.shift(1)).dropna()
            returns_dict[ticker] = log_ret

        # Combine into DataFrame with inner join
        df_returns = pd.DataFrame(returns_dict).dropna()

        if len(df_returns) < 252:
            raise ValueError(
                f"Aligned historical data has only {len(df_returns)} observations. "
                f"A minimum of 252 common trading days is required for period '{period}'."
            )

        return df_returns, provenance_dict

    @staticmethod
    def estimate_covariance(
        returns: np.ndarray,
        method: str = "ledoit_wolf"
    ) -> Tuple[np.ndarray, float, float]:
        """
        Estimates the annualized (252 days) covariance matrix.
        Uses Ledoit-Wolf (2004) analytical shrinkage towards the identity matrix
        scaled by the mean sample variance by default.
        """
        T, K = returns.shape
        S = np.cov(returns, rowvar=False)  # Sample covariance (daily)

        if method == "sample":
            Sigma_annual = S * 252.0
            cond_num = float(np.linalg.cond(Sigma_annual))
            return Sigma_annual, 0.0, cond_num

        # Ledoit-Wolf (2004) analytical shrinkage:
        # Target F = s_bar * I_K
        s_bar = float(np.trace(S) / K)
        F = s_bar * np.eye(K)

        # De-meaned returns
        X = returns - np.mean(returns, axis=0)

        # Frobenius norm squared of (S - F): delta^2 = ||S - F||_F^2
        delta_sq = float(np.sum((S - F) ** 2))

        if delta_sq < 1e-12:
            shrinkage_intensity = 0.0
            Sigma_shrunk = S
        else:
            # Asymptotic variance of sample covariance: pi_ij
            # pi_ij = (1/T) * sum_{t=1}^T (X_ti * X_tj - S_ij)^2
            # Vectorized computation of pi
            # X_outer: (T, K, K)
            X_outer = X[:, :, None] * X[:, None, :]  # shape: (T, K, K)
            diff = X_outer - S[None, :, :]
            pi = float(np.sum(np.mean(diff ** 2, axis=0)))

            # Optimal shrinkage intensity delta*
            shrinkage_intensity = float(np.clip((pi / T) / delta_sq, 0.0, 1.0))
            Sigma_shrunk = shrinkage_intensity * F + (1.0 - shrinkage_intensity) * S

        # Annualize
        Sigma_annual = Sigma_shrunk * 252.0
        cond_num = float(np.linalg.cond(Sigma_annual))
        return Sigma_annual, shrinkage_intensity, cond_num

    @staticmethod
    def estimate_expected_returns(
        returns: np.ndarray,
        tickers: List[str],
        Sigma: np.ndarray,
        mu_method: str = "historical_shrunk",
        forecast_horizon: int = 30
    ) -> Tuple[np.ndarray, List[str]]:
        """
        Estimates expected returns vector mu (annualized).
        Supports 'historical_shrunk' (James-Stein), 'equal' (global mean),
        or 'forecast' (implicit return from Damped Holt projection).
        """
        T, K = returns.shape
        warnings = []
        sample_mean = np.mean(returns, axis=0) * 252.0

        if mu_method == "equal":
            grand_mean = float(np.mean(sample_mean))
            mu = np.full(K, grand_mean)
            return mu, warnings

        elif mu_method == "forecast":
            warnings.append(
                "Usar retornos proyectados por modelos de series de tiempo como μ en Markowitz "
                "amplifica el error de estimación (Michaud, 1989)."
            )
            engine = DampedHoltForecastEngine()
            mu_forecast = np.zeros(K)

            for i, ticker in enumerate(tickers):
                series = MarketDataFetcher.get_history(ticker, period="1y")
                fc = engine.forecast(series.points, horizon=forecast_horizon, confidence=0.95)
                last_price = series.points[-1].value
                future_price = fc.values[-1]
                if last_price > 0 and future_price > 0:
                    # Annualized log return
                    annualized_ret = np.log(future_price / last_price) * (252.0 / forecast_horizon)
                    mu_forecast[i] = annualized_ret
                else:
                    mu_forecast[i] = sample_mean[i]
            return mu_forecast, warnings

        else:
            # Default: 'historical_shrunk' via James-Stein shrinkage
            grand_mean = float(np.mean(sample_mean))
            spread = float(np.sum((sample_mean - grand_mean) ** 2))
            mean_variance = float(np.trace(Sigma) / (K * T))

            if K > 2 and spread > 1e-8:
                shrink_factor = np.clip((K - 2) * mean_variance / spread, 0.0, 1.0)
            else:
                shrink_factor = 0.20  # Mild shrinkage for K=2

            mu = (1.0 - shrink_factor) * sample_mean + shrink_factor * grand_mean
            return mu, warnings

    @staticmethod
    def optimize_max_sharpe(
        mu: np.ndarray,
        Sigma: np.ndarray,
        max_weight: float = 0.35,
        rf: float = 0.045,
        n_restarts: int = 10,
        seed: int = 42
    ) -> np.ndarray:
        """
        Finds the tangency (Max Sharpe) portfolio using SLSQP with multiple
        Dirichlet random starts. Subject to sum(w) = 1 and 0 <= w_i <= max_weight.
        """
        K = len(mu)
        # Ensure feasibility: max_weight cannot be strictly less than 1/K
        effective_max_weight = max(max_weight, 1.0 / K)

        def neg_sharpe(w):
            port_ret = np.dot(w, mu)
            port_vol = np.sqrt(np.dot(w, np.dot(Sigma, w)))
            if port_vol < 1e-8:
                return 1e6
            return -(port_ret - rf) / port_vol

        bounds = [(0.0, effective_max_weight) for _ in range(K)]
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        rng = np.random.default_rng(seed)
        best_w = None
        best_fun = float("inf")

        for attempt in range(n_restarts):
            if attempt == 0:
                # First attempt: uniform weights
                w0 = np.full(K, 1.0 / K)
            else:
                # Dirichlet random start
                w0 = rng.dirichlet(np.ones(K))
                w0 = np.clip(w0, 0.0, effective_max_weight)
                w0 /= np.sum(w0)

            res = minimize(
                neg_sharpe,
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-9}
            )

            if res.success and res.fun < best_fun:
                best_fun = res.fun
                best_w = res.x

        if best_w is None:
            # Fallback to equal-weight if SLSQP completely fails
            best_w = np.full(K, 1.0 / K)

        # Normalize and clean small precision artefacts
        best_w = np.clip(best_w, 0.0, effective_max_weight)
        best_w /= np.sum(best_w)
        return best_w

    @staticmethod
    def optimize_risk_parity(Sigma: np.ndarray) -> np.ndarray:
        """
        Finds the Equal Risk Contribution (ERC / Risk Parity) portfolio
        using Spinu's (2013) convex formulation with a logarithmic barrier:
        min_w  (1/2) w^T Sigma w - (1/K) sum_{i=1}^K ln(w_i)
        followed by normalization w_final = w / sum(w).
        """
        K = Sigma.shape[0]

        def spinu_objective(w):
            quad = 0.5 * np.dot(w, np.dot(Sigma, w))
            log_barrier = (1.0 / K) * np.sum(np.log(np.maximum(w, 1e-12)))
            return quad - log_barrier

        def spinu_gradient(w):
            return np.dot(Sigma, w) - (1.0 / K) / np.maximum(w, 1e-12)

        # Inverse volatility initial guess
        inv_vol = 1.0 / np.sqrt(np.maximum(np.diag(Sigma), 1e-8))
        w0 = inv_vol / np.sum(inv_vol)

        bounds = [(1e-8, None) for _ in range(K)]

        res = minimize(
            spinu_objective,
            w0,
            jac=spinu_gradient,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500, "ftol": 1e-12, "gtol": 1e-9}
        )

        if res.success:
            w_opt = res.x
        else:
            w_opt = w0

        # Normalize to sum = 1
        w_final = w_opt / np.sum(w_opt)
        return w_final

    @staticmethod
    def compute_portfolio_metrics(
        w: np.ndarray,
        returns: np.ndarray,
        mu: np.ndarray,
        Sigma: np.ndarray,
        rf: float = 0.045
    ) -> Tuple[float, float, float, float, np.ndarray, np.ndarray, float]:
        """
        Calculates performance and risk attribution metrics:
        Expected return, volatility, Sharpe ratio, historical max drawdown,
        marginal risk contributions (RC_i), percentage RC_i, and Choueifaty DR.
        """
        exp_ret = float(np.dot(w, mu))
        port_vol = float(np.sqrt(np.maximum(np.dot(w, np.dot(Sigma, w)), 1e-12)))

        sharpe = float((exp_ret - rf) / port_vol) if port_vol > 1e-8 else 0.0

        # Marginal risk contribution: RC_i = w_i * (Sigma w)_i / sigma_p
        sigma_w = np.dot(Sigma, w)
        rc = (w * sigma_w) / port_vol if port_vol > 1e-8 else np.zeros_like(w)
        rc_pct = rc / port_vol if port_vol > 1e-8 else np.full_like(w, 1.0 / len(w))

        # Reconstructed historical returns for max drawdown
        port_daily_ret = np.dot(returns, w)
        cum_ret = np.exp(np.cumsum(port_daily_ret))
        running_max = np.maximum.accumulate(cum_ret)
        drawdown = (cum_ret - running_max) / running_max
        max_dd = float(np.min(drawdown))

        # Choueifaty Diversification Ratio: sum(w_i * sigma_i) / port_vol
        indiv_vols = np.sqrt(np.maximum(np.diag(Sigma), 1e-12))
        weighted_vol = float(np.dot(w, indiv_vols))
        dr = float(weighted_vol / port_vol) if port_vol > 1e-8 else 1.0

        return exp_ret, port_vol, sharpe, max_dd, rc, rc_pct, dr

    @classmethod
    def optimize_portfolio(cls, req: PortfolioOptimizeRequest) -> PortfolioOptimizeResponse:
        """Main execution method for portfolio optimization."""
        tickers = req.tickers
        K = len(tickers)

        # 1. Ingest and align historical returns
        df_returns, _ = cls.align_historical_returns(tickers, period=req.period)
        returns_arr = df_returns.values

        # 2. Estimate Covariance Matrix (Ledoit-Wolf or Sample)
        Sigma, shrinkage_intensity, cond_num = cls.estimate_covariance(
            returns_arr, method=req.cov_method
        )

        # 3. Estimate Expected Returns vector mu
        mu, warnings = cls.estimate_expected_returns(
            returns_arr,
            tickers,
            Sigma,
            mu_method=req.mu_method,
            forecast_horizon=req.forecast_horizon
        )

        # 4. Optimization Strategies
        # A. Max Sharpe
        w_sharpe = cls.optimize_max_sharpe(
            mu, Sigma, max_weight=req.max_weight, rf=req.risk_free_rate, seed=req.seed
        )

        # B. Risk Parity (Equal Risk Contribution)
        w_rp = cls.optimize_risk_parity(Sigma)

        # C. Equal Weight
        w_eq = np.full(K, 1.0 / K)

        # D. Current Weights (if provided, else equal-weight)
        if req.current_weights and all(t in req.current_weights for t in tickers):
            raw_w = np.array([req.current_weights[t] for t in tickers], dtype=float)
            total = np.sum(raw_w)
            w_curr = raw_w / total if total > 0 else w_eq.copy()
        else:
            w_curr = w_eq.copy()

        # 5. Build summary packages
        strategy_weights = {
            "max_sharpe": ("Cartera Óptima (Máx. Sharpe)", w_sharpe),
            "risk_parity": ("Paridad de Riesgo (ERC)", w_rp),
            "equal_weight": ("Cartera Equiponderada (1/K)", w_eq),
            "current": ("Cartera Actual", w_curr),
        }

        portfolios_summary = {}
        for key, (name, w) in strategy_weights.items():
            exp_ret, port_vol, sharpe, max_dd, rc, rc_pct, dr = cls.compute_portfolio_metrics(
                w, returns_arr, mu, Sigma, rf=req.risk_free_rate
            )

            weights_dict = {tickers[i]: round(float(w[i]), 4) for i in range(K)}
            rc_dict = {tickers[i]: round(float(rc[i]), 4) for i in range(K)}
            rc_pct_dict = {tickers[i]: round(float(rc_pct[i] * 100.0), 2) for i in range(K)}

            portfolios_summary[key] = PortfolioAllocationSummary(
                name=name,
                weights=weights_dict,
                expected_return=round(exp_ret, 4),
                volatility=round(port_vol, 4),
                sharpe_ratio=round(sharpe, 3),
                max_drawdown=round(max_dd, 4),
                risk_contributions=rc_dict,
                risk_contribution_pct=rc_pct_dict,
                diversification_ratio=round(dr, 3)
            )

        return PortfolioOptimizeResponse(
            tickers=tickers,
            shrinkage_intensity=round(shrinkage_intensity, 4),
            condition_number=round(cond_num, 2),
            mu_method_used=req.mu_method,
            cov_method_used=req.cov_method,
            portfolios=portfolios_summary,
            warnings=warnings
        )
