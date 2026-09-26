import logging
from typing import List, Optional
import numpy as np

from backend.schemas.models import (
    TimeSeriesPoint,
    BacktestMetrics,
    BacktestResponse,
)
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher
from backend.services.forecast_engine import BaseForecastEngine, get_forecast_engine

logger = logging.getLogger(__name__)

class BacktestEngine:
    """
    Backtesting engine evaluating model accuracy against ground-truth historical market data.
    Truncates data at T_cutoff, forecasts H steps forward, and computes step-wise directional
    accuracy, MAE, MAPE, sMAPE, MASE, interval coverage, and naive Random Walk benchmark.
    """

    @staticmethod
    def run_backtest(
        series_id: str,
        cutoff_date: str,
        horizon: int = 60,
        confidence: float = 0.95,
        is_macro: bool = False,
        engine_override: Optional[BaseForecastEngine] = None,
    ) -> BacktestResponse:
        """
        `engine_override`: forces a specific engine instance instead of the
        globally configured one (get_forecast_engine()) — used by
        EngineSelector's per-series auto-discovery mini-backtest (see
        backend/services/auto_discovery.py) to run Holt and TimesFM head-to-head
        on the SAME train/test split, which get_forecast_engine()'s single
        global choice can't do.
        """
        # 1. Fetch full historical series
        clean_id = series_id.strip().upper()
        if is_macro or clean_id in FREDDataFetcher.SERIES_CATALOG:
            data = FREDDataFetcher().get_series(clean_id)
        else:
            data = MarketDataFetcher.get_history(clean_id, period="5y")

        # Provenance guard: synthetic data cannot feed backtesting
        if getattr(data, "source", "live") == "synthetic":
            raise ValueError(f"La serie {clean_id} es sintética: no se puede validar una tesis sobre datos generados")

        points = data.points
        if len(points) < 30:
            raise ValueError(f"La serie {clean_id} no tiene suficientes datos históricos ({len(points)} puntos)")

        # Sort chronologically
        sorted_points = sorted(points, key=lambda p: p.timestamp)

        # 2. Split into train (t <= cutoff_date) and actual future (t > cutoff_date)
        train_points = [p for p in sorted_points if p.timestamp <= cutoff_date]
        future_actual_points = [p for p in sorted_points if p.timestamp > cutoff_date]

        if len(train_points) < 15:
            raise ValueError(f"Fecha de corte {cutoff_date} deja muy pocos datos de entrenamiento ({len(train_points)} puntos)")

        if len(future_actual_points) == 0:
            raise ValueError(f"No existen datos reales posteriores a la fecha de corte {cutoff_date} para auditar")

        # Limit future comparison to requested horizon
        actual_eval_points = future_actual_points[:horizon]
        eval_horizon = len(actual_eval_points)

        # 3. Run forecast engine on training data
        engine = engine_override if engine_override is not None else get_forecast_engine()
        freq = "M" if data.type == "macro" else "D"
        forecast_res = engine.forecast(
            train_points,
            horizon=eval_horizon,
            confidence=confidence,
            freq=freq
        )

        # 4. Calculate error metrics on the overlap
        y_actual = np.array([p.value for p in actual_eval_points], dtype=float)
        y_pred = np.array(forecast_res.values[:eval_horizon], dtype=float)
        lbs = np.array(forecast_res.lower_bound[:eval_horizon], dtype=float)
        ubs = np.array(forecast_res.upper_bound[:eval_horizon], dtype=float)

        # MAE: Mean Absolute Error
        mae = float(np.mean(np.abs(y_actual - y_pred)))

        # MAPE with absolute denominator: safe for negative or near-zero series
        epsilon = 1e-8
        mape = float(np.mean(np.abs((y_actual - y_pred) / (np.abs(y_actual) + epsilon))) * 100)

        # sMAPE: Symmetric Mean Absolute Percentage Error
        smape = float(np.mean(2.0 * np.abs(y_actual - y_pred) / (np.abs(y_actual) + np.abs(y_pred) + epsilon)) * 100)

        # MASE: Mean Absolute Scaled Error relative to in-sample 1-step naive forecast
        y_train_vals = np.array([p.value for p in train_points], dtype=float)
        if len(y_train_vals) > 1:
            in_sample_naive_mae = float(np.mean(np.abs(np.diff(y_train_vals))))
            mase = float(mae / (in_sample_naive_mae + epsilon))
        else:
            in_sample_naive_mae = 1.0
            mase = 1.0

        # Step-by-step directional accuracy
        if eval_horizon > 1:
            actual_diffs = np.diff(y_actual)
            pred_diffs = np.diff(y_pred)
            step_matches = np.sign(actual_diffs) == np.sign(pred_diffs)
            directional_accuracy = float(np.mean(step_matches) * 100)
        else:
            directional_accuracy = 50.0

        # Aggregate horizon directional accuracy
        y_train_last = train_points[-1].value
        aggregate_direction_correct = bool(
            np.sign(y_actual[-1] - y_train_last) == np.sign(y_pred[-1] - y_train_last)
        )

        # Interval coverage: percentage of actual observations falling within [LB, UB]
        in_interval = (y_actual >= lbs) & (y_actual <= ubs)
        interval_coverage = float(np.mean(in_interval) * 100)

        # 5. Mandatory Naive Random Walk Benchmark (y_hat = y_{train_last})
        y_naive = np.full_like(y_actual, y_train_last)
        naive_mae = float(np.mean(np.abs(y_actual - y_naive)))
        naive_mape = float(np.mean(np.abs((y_actual - y_naive) / (np.abs(y_actual) + epsilon))) * 100)
        naive_smape = float(np.mean(2.0 * np.abs(y_actual - y_naive) / (np.abs(y_actual) + np.abs(y_naive) + epsilon)) * 100)
        naive_mase = float(naive_mae / (in_sample_naive_mae + epsilon))

        naive_metrics = BacktestMetrics(
            mae=round(naive_mae, 2),
            mape=round(naive_mape, 2),
            smape=round(naive_smape, 2),
            mase=round(naive_mase, 3),
            directional_accuracy=0.0,
            observations_evaluated=eval_horizon
        )

        # 6. Verdict and Warnings
        warnings: List[str] = []
        # TimesFMForecastEngine.forecast() catches its own inference errors and
        # answers with Holt (is_fallback=True). Without surfacing that here,
        # these metrics would be reported as the requested engine's.
        is_fallback = bool(forecast_res.is_fallback)
        if is_fallback:
            warnings.append(
                f"El motor pedido no corrió: la predicción la hizo {forecast_res.model_name}. "
                f"Estas métricas son de Holt, no de TimesFM."
            )
        nominal_coverage = confidence * 100.0
        if interval_coverage < (nominal_coverage - 15.0):
            warnings.append(
                f"Subcobertura del intervalo: La cobertura empírica observada ({interval_coverage:.1f}%) "
                f"está sustancialmente por debajo del nivel nominal solicitado ({nominal_coverage:.0f}%)."
            )

        if mae < naive_mae:
            mae_improvement = ((naive_mae - mae) / (naive_mae + epsilon)) * 100.0
            verdict = (
                f"El modelo supera al benchmark naive (Random Walk) reduciendo el MAE un {mae_improvement:.1f}% "
                f"(MAE Modelo: {mae:.2f} vs Naive: {naive_mae:.2f} {data.unit}). "
                f"Acierto direccional paso a paso: {directional_accuracy:.1f}%, Cobertura: {interval_coverage:.1f}%."
            )
        else:
            verdict = (
                f"El modelo NO supera al benchmark naive (Random Walk). "
                f"El error del modelo (MAE {mae:.2f} {data.unit}) es superior a la persistencia naive ({naive_mae:.2f} {data.unit}). "
                f"Calibración deficiente frente a la inercia del último precio observado."
            )

        display_train = train_points[-120:]

        return BacktestResponse(
            series_id=clean_id,
            cutoff_date=cutoff_date,
            horizon=eval_horizon,
            historical_dates=[p.timestamp for p in display_train],
            historical_values=[p.value for p in display_train],
            future_actual_dates=[p.timestamp for p in actual_eval_points],
            future_actual_values=[p.value for p in actual_eval_points],
            future_predicted_values=[round(float(v), 2) for v in y_pred],
            future_lower_bound=[round(float(v), 2) for v in lbs],
            future_upper_bound=[round(float(v), 2) for v in ubs],
            metrics=BacktestMetrics(
                mae=round(mae, 2),
                mape=round(mape, 2),
                smape=round(smape, 2),
                mase=round(mase, 3),
                directional_accuracy=round(directional_accuracy, 1),
                observations_evaluated=eval_horizon
            ),
            naive_metrics=naive_metrics,
            interval_coverage=round(interval_coverage, 1),
            aggregate_direction_correct=aggregate_direction_correct,
            verdict=verdict,
            warnings=warnings,
            model_name=forecast_res.model_name,
            is_fallback=is_fallback,
        )
