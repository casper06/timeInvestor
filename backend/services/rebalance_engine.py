"""
TimeInvestor - Walk-Forward Portfolio Rebalancing & Transaction Cost Engine
==========================================================================
Implements walk-forward historical simulation with:
1. Strict zero look-ahead bias: Covariance and weights at date t use only history up to t.
2. Rebalance frequencies: monthly (~21 trading days), quarterly (~63 trading days), or none (buy-and-hold).
3. Realistic turnover and transaction costs: turnover * cost_bps / 10,000.
4. Capital gains tax approximation: linear estimation on realized sales.
5. Three simultaneous curves: Rebalance Net, Rebalance Gross, and Buy-and-Hold.
6. Objective, transparent verdict comparing net benefit vs buy-and-hold.
"""

import logging
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd

from backend.schemas.models import (
    RebalanceBacktestRequest,
    RebalanceBacktestResponse,
    RebalanceCurvePoint,
    StrategyPerformanceMetrics,
)
from backend.services.data_fetcher import MarketDataFetcher
from backend.services.portfolio_engine import PortfolioEngine

logger = logging.getLogger("TimeInvestor.RebalanceEngine")


class RebalanceEngine:
    """Simulates dynamic portfolio rebalancing with friction and tax modeling."""

    @staticmethod
    def align_historical_prices(
        tickers: List[str],
        period: str = "5y"
    ) -> Tuple[pd.DataFrame, Dict[str, str]]:
        """
        Fetches historical price data for each ticker, verifies data provenance,
        and aligns all tickers via an inner join on date.
        Rejects synthetic data with ValueError.
        """
        prices_dict = {}
        provenance_dict = {}

        for ticker in tickers:
            series = MarketDataFetcher.get_history(ticker, period=period)
            if series.source == "synthetic":
                raise ValueError(
                    f"Ticker '{ticker}' contains synthetic data. "
                    "Rebalance backtest requires live or cached market data."
                )
            provenance_dict[ticker] = series.source

            if len(series.points) < 2:
                raise ValueError(f"Insufficient historical data points for ticker '{ticker}'")

            dates = [p.timestamp for p in series.points]
            values = [p.value for p in series.points]
            s = pd.Series(values, index=pd.to_datetime(dates), name=ticker).sort_index()
            s = s[~s.index.duplicated(keep="last")]
            prices_dict[ticker] = s

        df_prices = pd.DataFrame(prices_dict).dropna().sort_index()

        if len(df_prices) < 252:
            raise ValueError(
                f"Aligned historical data has only {len(df_prices)} common trading days. "
                "A minimum of 252 trading days is required for walk-forward backtesting."
            )

        return df_prices, provenance_dict

    @staticmethod
    def calculate_strategy_metrics(
        values: np.ndarray,
        rf: float = 0.045
    ) -> StrategyPerformanceMetrics:
        """
        Computes Total Return, CAGR, Annualized Volatility, Sharpe Ratio,
        and Historical Maximum Drawdown for an equity curve.
        """
        if len(values) < 2:
            return StrategyPerformanceMetrics(
                total_return=0.0,
                annualized_return=0.0,
                annualized_volatility=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
            )

        v_0 = float(values[0])
        v_end = float(values[-1])
        m = len(values) - 1

        total_return = float(v_end / v_0 - 1.0) if v_0 > 0 else 0.0

        if m > 0 and v_end > 0 and v_0 > 0:
            annualized_return = float((v_end / v_0) ** (252.0 / m) - 1.0)
        else:
            annualized_return = total_return

        daily_returns = np.diff(values) / np.maximum(values[:-1], 1e-12)
        daily_vol = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else 0.0
        annualized_vol = float(daily_vol * np.sqrt(252.0))

        if annualized_vol > 1e-8:
            sharpe = float((annualized_return - rf) / annualized_vol)
        else:
            sharpe = 0.0

        peaks = np.maximum.accumulate(values)
        drawdowns = (values - peaks) / np.maximum(peaks, 1e-12)
        max_dd = float(np.min(drawdowns))

        return StrategyPerformanceMetrics(
            total_return=round(total_return, 4),
            annualized_return=round(annualized_return, 4),
            annualized_volatility=round(annualized_vol, 4),
            sharpe_ratio=round(sharpe, 3),
            max_drawdown=round(max_dd, 4),
        )

    @classmethod
    def compute_weights_at_step(
        cls,
        returns_window: np.ndarray,
        tickers: List[str],
        method: str,
        mu_method: str,
        max_weight: float,
        rf: float
    ) -> np.ndarray:
        """
        Optimizes weights using strictly past data (returns_window).
        Guarantees zero look-ahead bias.
        """
        sigma, _, _ = PortfolioEngine.estimate_covariance(returns_window, method="ledoit_wolf")

        if method == "risk_parity":
            return PortfolioEngine.optimize_risk_parity(sigma)
        else:
            # Default to max_sharpe
            mu, _ = PortfolioEngine.estimate_expected_returns(
                returns_window, tickers, sigma, mu_method=mu_method
            )
            return PortfolioEngine.optimize_max_sharpe(
                mu, sigma, max_weight=max_weight, rf=rf
            )

    @classmethod
    def run_rebalance_backtest(
        cls,
        req: RebalanceBacktestRequest
    ) -> RebalanceBacktestResponse:
        """
        Executes walk-forward backtest comparing:
        1. Rebalance Net (with transaction costs and capital gains tax).
        2. Rebalance Gross (same rebalance weights, zero friction).
        3. Buy-and-Hold (initial weights from t_start, drifted, zero intermediate friction).
        """
        tickers = req.tickers
        k = len(tickers)

        # 1. Ingest and align historical price matrix
        df_prices, _ = cls.align_historical_prices(tickers, period=req.period)
        dates = [d.strftime("%Y-%m-%d") for d in df_prices.index]
        p_mat = df_prices.values
        n_days = len(dates)

        # 2. Compute log returns for weight estimation
        # log_returns[t] is ln(P_t / P_{t-1})
        log_ret_mat = np.log(p_mat[1:] / np.maximum(p_mat[:-1], 1e-12))

        # 3. Determine burn-in window and evaluation horizon
        burn_in = min(req.burn_in_days, n_days - 22)
        burn_in = max(burn_in, 126)  # At least half year burn-in

        if n_days - burn_in < 21:
            raise ValueError(
                f"Evaluation horizon too short ({n_days - burn_in} days). "
                f"Increase history period or reduce burn_in_days."
            )

        t_start = burn_in

        # 4. Initial Portfolio Setup at t_start
        # Calculate initial weights using ONLY history up to t_start
        init_returns_window = log_ret_mat[max(0, t_start - 252) : t_start]
        w_0 = cls.compute_weights_at_step(
            init_returns_window,
            tickers,
            method=req.method,
            mu_method=req.mu_method,
            max_weight=req.max_weight,
            rf=req.risk_free_rate,
        )

        w_net = w_0.copy()
        w_gross = w_0.copy()
        w_bnh = w_0.copy()

        v_net = float(req.initial_capital)
        v_gross = float(req.initial_capital)
        v_bnh = float(req.initial_capital)

        # Cost basis per asset for net portfolio
        cost_basis_net = p_mat[t_start].copy()

        # Telemetry accumulators
        total_turnover = 0.0
        total_costs = 0.0
        total_tax = 0.0
        n_rebalances = 0

        # Storage for curves and metrics
        curves: List[RebalanceCurvePoint] = [
            RebalanceCurvePoint(
                date=dates[t_start],
                rebalance_net=round(v_net, 2),
                rebalance_gross=round(v_gross, 2),
                buy_and_hold=round(v_bnh, 2),
            )
        ]
        net_values = [v_net]
        gross_values = [v_gross]
        bnh_values = [v_bnh]

        # 5. Walk-Forward Simulation Loop
        for t in range(t_start + 1, n_days):
            # Daily asset simple returns between day t-1 and day t
            p_prev = p_mat[t - 1]
            p_curr = p_mat[t]
            r_daily = (p_curr - p_prev) / np.maximum(p_prev, 1e-12)

            # A. Daily drift before rebalancing at close of day t
            r_net_port = float(np.dot(w_net, r_daily))
            v_net = v_net * (1.0 + r_net_port)
            w_net_drifted = (w_net * (1.0 + r_daily)) / (1.0 + r_net_port)

            r_gross_port = float(np.dot(w_gross, r_daily))
            v_gross = v_gross * (1.0 + r_gross_port)
            w_gross_drifted = (w_gross * (1.0 + r_daily)) / (1.0 + r_gross_port)

            r_bnh_port = float(np.dot(w_bnh, r_daily))
            v_bnh = v_bnh * (1.0 + r_bnh_port)
            w_bnh_drifted = (w_bnh * (1.0 + r_daily)) / (1.0 + r_bnh_port)
            w_bnh = w_bnh_drifted  # Buy and hold never rebalances

            # B. Check if day t is a scheduled rebalance date
            is_rebalance_day = False
            if req.rebalance_frequency == "monthly" and (t - t_start) % 21 == 0:
                is_rebalance_day = True
            elif req.rebalance_frequency == "quarterly" and (t - t_start) % 63 == 0:
                is_rebalance_day = True

            if not is_rebalance_day:
                w_net = w_net_drifted
                w_gross = w_gross_drifted
            else:
                n_rebalances += 1

                # Re-optimize target weights using STRICTLY past data up to t
                # Lookback window: up to 252 days ending at t-1 (or t in log_ret_mat)
                hist_window = log_ret_mat[max(0, t - 252) : t]
                w_target = cls.compute_weights_at_step(
                    hist_window,
                    tickers,
                    method=req.method,
                    mu_method=req.mu_method,
                    max_weight=req.max_weight,
                    rf=req.risk_free_rate,
                )

                # Turnover: sum |w_new, i - w_curr, i|
                turnover_t = float(np.sum(np.abs(w_target - w_net_drifted)))
                total_turnover += turnover_t

                # Transaction cost: turnover * cost_bps / 10,000 * Portfolio Value
                cost_t = turnover_t * (req.cost_bps / 10000.0) * v_net
                total_costs += cost_t

                # Capital gains tax estimation on realized sales
                tax_t = 0.0
                if req.capital_gains_tax_rate > 0.0:
                    for i in range(k):
                        if w_target[i] < w_net_drifted[i]:
                            sold_frac = w_net_drifted[i] - w_target[i]
                            dollars_sold = sold_frac * v_net
                            entry_price = cost_basis_net[i]
                            current_price = p_curr[i]
                            if current_price > entry_price and entry_price > 0:
                                gain_fraction = (current_price - entry_price) / current_price
                                realized_gain = dollars_sold * gain_fraction
                                tax_t += realized_gain * req.capital_gains_tax_rate
                    total_tax += tax_t

                # Deduct friction from net portfolio
                v_net = max(0.0, v_net - cost_t - tax_t)
                w_net = w_target.copy()
                w_gross = w_target.copy()

                # Update cost basis for bought assets
                for i in range(k):
                    if w_target[i] > w_net_drifted[i]:
                        cost_basis_net[i] = p_curr[i]

            net_values.append(v_net)
            gross_values.append(v_gross)
            bnh_values.append(v_bnh)

            curves.append(
                RebalanceCurvePoint(
                    date=dates[t],
                    rebalance_net=round(v_net, 2),
                    rebalance_gross=round(v_gross, 2),
                    buy_and_hold=round(v_bnh, 2),
                )
            )

        # 6. Performance Metrics
        net_metrics = cls.calculate_strategy_metrics(np.array(net_values), rf=req.risk_free_rate)
        gross_metrics = cls.calculate_strategy_metrics(np.array(gross_values), rf=req.risk_free_rate)
        bnh_metrics = cls.calculate_strategy_metrics(np.array(bnh_values), rf=req.risk_free_rate)

        net_benefit = round(net_metrics.annualized_return - bnh_metrics.annualized_return, 4)
        cost_drag = round(gross_metrics.annualized_return - net_metrics.annualized_return, 4)
        years_eval = round(len(net_values) / 252.0, 1)

        # 7. Honest Quantitative Verdict
        if req.rebalance_frequency == "none":
            verdict = (
                f"Modo Buy-and-Hold evaluado a lo largo de {years_eval} años: "
                f"Retorno anualizado de {bnh_metrics.annualized_return * 100:.2f}% con Sharpe {bnh_metrics.sharpe_ratio:.2f} "
                f"y Max Drawdown de {bnh_metrics.max_drawdown * 100:.2f}%. No se ejecutaron rebalanceos ni se devengaron fricciones."
            )
        elif net_benefit < 0:
            verdict = (
                f"En este período de {years_eval} años, rebalancear {req.rebalance_frequency} costó más de lo que aportó: "
                f"el drag acumulado por costos de transacción e impuestos ({cost_drag * 100:.2f}% anual) superó "
                f"el beneficio de diversificación. Buy-and-Hold fue superior por {abs(net_benefit) * 100:.2f}% "
                f"de retorno anualizado (Sharpe BnH: {bnh_metrics.sharpe_ratio:.2f} vs Sharpe Neto: {net_metrics.sharpe_ratio:.2f})."
            )
        else:
            verdict = (
                f"En este período de {years_eval} años, rebalancear {req.rebalance_frequency} aportó un beneficio neto positivo: "
                f"superó a Buy-and-Hold por {net_benefit * 100:.2f}% de retorno anualizado neto de costos "
                f"(Sharpe Neto: {net_metrics.sharpe_ratio:.2f} vs Sharpe BnH: {bnh_metrics.sharpe_ratio:.2f}). "
                f"El arrastre acumulado por fricciones fue de ${total_costs + total_tax:,.2f} ({cost_drag * 100:.2f}% anual de drag)."
            )

        # 8. Regulatory and Technical Warnings
        warnings = []
        if req.capital_gains_tax_rate > 0.0:
            warnings.append(
                "Aproximación lineal de impuesto sobre ganancias de capital en ventas; "
                "no modela lotes fiscales específicos (FIFO/LIFO)."
            )
        if n_rebalances == 0 and req.rebalance_frequency != "none":
            warnings.append("No se ejecutaron rebalanceos en el período evaluado debido a una ventana temporal corta.")

        return RebalanceBacktestResponse(
            tickers=tickers,
            method=req.method,
            rebalance_frequency=req.rebalance_frequency,
            cost_bps=req.cost_bps,
            capital_gains_tax_rate=req.capital_gains_tax_rate,
            initial_capital=req.initial_capital,
            start_date=dates[t_start],
            end_date=dates[-1],
            trading_days_evaluated=len(net_values),
            n_rebalances_executed=n_rebalances,
            total_turnover=round(total_turnover, 4),
            total_transaction_costs=round(total_costs, 2),
            total_tax_paid=round(total_tax, 2),
            curves=curves,
            net_metrics=net_metrics,
            gross_metrics=gross_metrics,
            buy_and_hold_metrics=bnh_metrics,
            net_benefit_of_rebalancing=net_benefit,
            cost_drag=cost_drag,
            verdict=verdict,
            warnings=warnings,
        )
