"""
TimeInvestor - Portfolio Risk Engine (Monte Carlo, Bootstrap, and VaR/CVaR)
===========================================================================
Implements multi-asset risk evaluation:
1. Block bootstrap (preserves fat tails and empirical correlation).
2. Student-t simulation (leptokurtic shock modelling).
3. Parametric Gaussian Monte Carlo with Higham/eigenvalue clipping for PSD Cholesky.
4. Positive loss convention: VaR_95 = 0.12 means 12% maximum loss at 95% confidence.
5. Invariant CVaR >= VaR (Expected Shortfall).
6. Monte Carlo Standard Error via KDE density at quantile.
7. Histogram distribution data and probability of loss threshold exceedances.
"""

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy import stats

from backend.schemas.models import (
    PortfolioRiskRequest,
    PortfolioRiskResponse,
    RiskMetricDetail,
    HistogramData,
)
from backend.services.data_fetcher import MarketDataFetcher

logger = logging.getLogger("TimeInvestor.RiskEngine")


class RiskEngine:
    """Quantitative risk engine for multi-asset portfolios."""

    @staticmethod
    def align_historical_returns(
        tickers: List[str],
        period: str = "2y"
    ) -> Tuple[np.ndarray, List[str]]:
        """
        Ingests data, rejects synthetic series, computes log-returns,
        and aligns by date using an inner join.
        """
        returns_dict = {}
        for ticker in tickers:
            series = MarketDataFetcher.get_history(ticker, period=period)
            if series.source == "synthetic":
                raise ValueError(
                    f"Ticker '{ticker}' contains synthetic data. "
                    "Risk analysis requires live or cached market data."
                )
            if len(series.points) < 2:
                raise ValueError(f"Insufficient data for ticker '{ticker}'")

            dates = [p.timestamp for p in series.points]
            prices = [p.value for p in series.points]
            s = pd.Series(prices, index=pd.to_datetime(dates), name=ticker).sort_index()
            s = s[~s.index.duplicated(keep="last")]
            log_ret = np.log(s / s.shift(1)).dropna()
            returns_dict[ticker] = log_ret

        df_returns = pd.DataFrame(returns_dict).dropna()
        if len(df_returns) < 252:
            raise ValueError(
                f"Aligned historical data has only {len(df_returns)} observations. "
                "A minimum of 252 trading days is required."
            )

        return df_returns.values, list(df_returns.columns)

    @staticmethod
    def ensure_psd(matrix: np.ndarray, min_eigenval: float = 1e-8) -> np.ndarray:
        """Applies eigenvalue clipping to ensure matrix is positive semi-definite."""
        eigvals, eigvecs = np.linalg.eigh(matrix)
        clipped_eigvals = np.maximum(eigvals, min_eigenval)
        psd_matrix = eigvecs @ np.diag(clipped_eigvals) @ eigvecs.T
        # Symmetrize
        return (psd_matrix + psd_matrix.T) / 2.0

    @classmethod
    def simulate_bootstrap(
        cls,
        returns: np.ndarray,
        w: np.ndarray,
        horizon: int,
        n_simulations: int,
        block_size: Optional[int] = None,
        seed: int = 42
    ) -> np.ndarray:
        """
        Vectorized Block Bootstrap simulation.
        Preserves joint empirical correlation and heavy tails.
        Returns cumulative portfolio simple returns array of shape (N,).
        """
        T, K = returns.shape
        b = block_size if block_size is not None else max(5, int(np.ceil(horizon ** (1.0 / 3.0))))
        b = min(b, T - 1)

        rng = np.random.default_rng(seed)
        num_blocks = int(np.ceil(horizon / b))

        # Random start indices for all blocks: shape (N, num_blocks)
        start_indices = rng.integers(0, T - b + 1, size=(n_simulations, num_blocks))

        # Build block offsets: shape (b,)
        block_offsets = np.arange(b)

        # Time indices: shape (N, num_blocks, b) -> flattened to (N, num_blocks * b)
        sampled_time_indices = (start_indices[:, :, None] + block_offsets[None, None, :]).reshape(n_simulations, -1)

        # Truncate to exact horizon H
        sampled_time_indices = sampled_time_indices[:, :horizon]

        # Gather returns: shape (N, H, K)
        simulated_returns = returns[sampled_time_indices]  # shape: (N, H, K)

        # Portfolio daily log-returns: shape (N, H)
        port_daily_log_returns = np.dot(simulated_returns, w)

        # Cumulative log-returns: shape (N,)
        port_cum_log_returns = np.sum(port_daily_log_returns, axis=1)

        # Convert to simple returns: R = exp(r) - 1
        return np.exp(port_cum_log_returns) - 1.0

    @classmethod
    def simulate_student_t(
        cls,
        returns: np.ndarray,
        w: np.ndarray,
        horizon: int,
        n_simulations: int,
        seed: int = 42
    ) -> Tuple[np.ndarray, Optional[str]]:
        """
        Student-t distribution simulation over portfolio returns.
        Falls back to Gaussian if degrees of freedom > 30.
        """
        port_hist_returns = np.dot(returns, w)
        warning_msg = None

        try:
            df_fit, loc_fit, scale_fit = stats.t.fit(port_hist_returns)
            if df_fit > 30.0:
                warning_msg = (
                    f"Grados de libertad estimados ν = {df_fit:.1f} > 30; "
                    "la distribución Student-t converge asintóticamente a la Gaussiana."
                )
                df_fit = None
        except Exception:
            df_fit = None
            warning_msg = "Ajuste de distribución Student-t no convergió; aplicando fallback normal."

        rng = np.random.default_rng(seed)

        if df_fit is None or df_fit <= 2.0:
            # Fallback to normal
            daily_mean = np.mean(port_hist_returns)
            daily_std = np.std(port_hist_returns)
            shocks = rng.normal(daily_mean, daily_std, size=(n_simulations, horizon))
        else:
            # Standard t shocks scaled to empirical variance
            t_shocks = rng.standard_t(df=df_fit, size=(n_simulations, horizon))
            # Variance of t_df is df / (df - 2)
            t_std = np.sqrt(df_fit / (df_fit - 2.0))
            daily_std = np.std(port_hist_returns)
            daily_mean = np.mean(port_hist_returns)
            shocks = daily_mean + (t_shocks / t_std) * daily_std

        cum_log_returns = np.sum(shocks, axis=1)
        return np.exp(cum_log_returns) - 1.0, warning_msg

    @classmethod
    def simulate_gaussian(
        cls,
        returns: np.ndarray,
        w: np.ndarray,
        horizon: int,
        n_simulations: int,
        seed: int = 42
    ) -> Tuple[np.ndarray, str]:
        """
        Vectorized Parametric Gaussian Monte Carlo simulation.
        Guarantees PSD covariance via eigenvalue clipping before Cholesky decomposition.
        """
        warning_msg = "El método gaussiano subestima sistemáticamente el riesgo de cola (kurtosis)."
        T, K = returns.shape
        mu_daily = np.mean(returns, axis=0)
        Sigma_daily = np.cov(returns, rowvar=False)

        # Enforce PSD
        Sigma_psd = cls.ensure_psd(Sigma_daily, min_eigenval=1e-8)

        # Cholesky factor: L such that L @ L.T = Sigma_psd
        try:
            L = np.linalg.cholesky(Sigma_psd)
        except np.linalg.LinAlgError:
            # Stronger eigenvalue floor if extreme collinearity
            Sigma_psd = cls.ensure_psd(Sigma_daily, min_eigenval=1e-5)
            L = np.linalg.cholesky(Sigma_psd)

        rng = np.random.default_rng(seed)
        # Generate standard normal shocks: shape (N, H, K)
        Z = rng.standard_normal(size=(n_simulations, horizon, K))

        # Correlated shocks: Z @ L.T -> shape (N, H, K)
        correlated_shocks = np.einsum("nhk,jk->nhj", Z, L) + mu_daily[None, None, :]

        # Portfolio daily returns: shape (N, H)
        port_daily = np.dot(correlated_shocks, w)

        # Cumulative log-returns: shape (N,)
        cum_log_returns = np.sum(port_daily, axis=1)

        return np.exp(cum_log_returns) - 1.0, warning_msg

    @staticmethod
    def compute_kde_density(data: np.ndarray, eval_point: float) -> float:
        """Computes Gaussian KDE density at a specific point for SE calculation."""
        try:
            kde = stats.gaussian_kde(data)
            density = float(kde(eval_point)[0])
            return max(density, 1e-6)
        except Exception:
            std_val = float(np.std(data))
            if std_val < 1e-8:
                return 1.0
            return float(stats.norm.pdf(eval_point, loc=np.mean(data), scale=std_val))

    @classmethod
    def evaluate_risk(cls, req: PortfolioRiskRequest) -> PortfolioRiskResponse:
        """Main execution method for portfolio risk evaluation."""
        tickers = req.tickers
        K = len(tickers)

        # 1. Ingest and align historical returns
        returns_arr, aligned_tickers = cls.align_historical_returns(tickers)

        # 2. Normalize weights to vector aligned with tickers
        w_vec = np.array([req.weights.get(t, 0.0) for t in aligned_tickers], dtype=float)
        sum_w = np.sum(w_vec)
        if sum_w <= 0.0:
            w_vec = np.full(K, 1.0 / K)
        else:
            w_vec /= sum_w

        warnings_list = []

        # 3. Simulate return distribution over horizon H
        if req.method == "bootstrap":
            portfolio_returns = cls.simulate_bootstrap(
                returns_arr, w_vec, req.horizon_days, req.n_simulations, req.block_size
            )
        elif req.method == "student_t":
            portfolio_returns, warn = cls.simulate_student_t(
                returns_arr, w_vec, req.horizon_days, req.n_simulations
            )
            if warn:
                warnings_list.append(warn)
        else:
            # Gaussian
            portfolio_returns, warn = cls.simulate_gaussian(
                returns_arr, w_vec, req.horizon_days, req.n_simulations
            )
            warnings_list.append(warn)

        # 4. Positive Loss Convention: L = - R_p
        losses = - portfolio_returns
        N = len(losses)

        # 5. Metrics calculation for each confidence level (e.g. 0.95, 0.99)
        metrics_dict = {}
        for conf in req.confidence_levels:
            conf_pct = conf * 100.0
            label = f"{int(conf_pct)}%"

            # VaR as positive loss quantile
            var_val = float(np.percentile(losses, conf_pct))

            # CVaR (Expected Shortfall): mean of losses >= VaR
            exceedances = losses[losses >= var_val]
            cvar_val = float(np.mean(exceedances)) if len(exceedances) > 0 else var_val

            # Invariant assertion
            if cvar_val < var_val:
                cvar_val = var_val

            # Monte Carlo Standard Error for VaR:
            # SE = sqrt(p * (1-p)) / (N * f(VaR))
            f_var = cls.compute_kde_density(losses, var_val)
            se_var = float(np.sqrt(conf * (1.0 - conf)) / (np.sqrt(N) * f_var))

            if var_val > 0.01 and (se_var / var_val) > 0.15:
                warnings_list.append(
                    f"El error estándar de Monte Carlo ({se_var:.4f}) supera el 15% del VaR {label} ({var_val:.4f}). "
                    "Considere aumentar N_simulations o reducir el horizonte."
                )

            var_usd = float(var_val * req.initial_capital)
            cvar_usd = float(cvar_val * req.initial_capital)

            metrics_dict[label] = RiskMetricDetail(
                confidence_level=conf,
                var_pct=round(var_val, 4),
                var_usd=round(var_usd, 2),
                var_std_error=round(se_var, 5),
                cvar_pct=round(cvar_val, 4),
                cvar_usd=round(cvar_usd, 2),
            )

        # 6. Tail probabilities of loss threshold exceedance
        prob_loss_10 = float(np.mean(losses > 0.10))
        prob_loss_20 = float(np.mean(losses > 0.20))
        prob_loss_30 = float(np.mean(losses > 0.30))

        # 7. Histogram preparation (30 bins on portfolio returns)
        counts, bin_edges = np.histogram(portfolio_returns, bins=30)
        densities, _ = np.histogram(portfolio_returns, bins=30, density=True)

        hist_data = HistogramData(
            bin_edges=[round(float(e), 5) for e in bin_edges],
            frequencies=[int(c) for c in counts],
            densities=[round(float(d), 5) for d in densities],
            median=round(float(np.median(portfolio_returns)), 4),
            percentile_5=round(float(np.percentile(portfolio_returns, 5.0)), 4),
            percentile_1=round(float(np.percentile(portfolio_returns, 1.0)), 4),
        )

        return PortfolioRiskResponse(
            method_used=req.method,
            horizon_days=req.horizon_days,
            initial_capital=req.initial_capital,
            n_simulations=req.n_simulations,
            metrics=metrics_dict,
            prob_loss_10pct=round(prob_loss_10, 4),
            prob_loss_20pct=round(prob_loss_20, 4),
            prob_loss_30pct=round(prob_loss_30, 4),
            histogram=hist_data,
            warnings=warnings_list
        )
