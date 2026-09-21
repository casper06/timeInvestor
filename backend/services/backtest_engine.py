import logging
from typing import List, Optional
import numpy as np

from backend.schemas.models import (
    TimeSeriesPoint,
    BacktestMetrics,
    BacktestResponse,
)
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher
from backend.services.forecast_engine import get_forecast_engine

logger = logging.getLogger(__name__)

class BacktestEngine:
    """
    Backtesting engine evaluating model accuracy against ground-truth historical market data.
    Truncates data at T_cutoff, forecasts H steps forward, and computes MAE, MAPE, and Directional Accuracy.
    """

    @staticmethod
    def run_backtest(
        series_id: str,
        cutoff_date: str,
        horizon: int = 60,
        confidence: float = 0.95,
        is_macro: bool = False,
    ) -> BacktestResponse:
        # 1. Fetch full historical series
        if is_macro or series_id.upper() in FREDDataFetcher.SERIES_CATALOG:
            data = FREDDataFetcher().get_series(series_id)
        else:
            data = MarketDataFetcher.get_history(series_id, period="5y")

        points = data.points
        if len(points) < 30:
            raise ValueError(f"La serie {series_id} no tiene suficientes datos históricos ({len(points)} puntos)")

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
        engine = get_forecast_engine()
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

        # MAE: Mean Absolute Error
        mae = float(np.mean(np.abs(y_actual - y_pred)))

        # MAPE: Mean Absolute Percentage Error
        epsilon = 1e-6
        mape = float(np.mean(np.abs((y_actual - y_pred) / (y_actual + epsilon))) * 100)

        # Directional Accuracy (% of times the predicted sign of return matches actual return from last train point)
        y0 = train_points[-1].value
        actual_dir = np.sign(y_actual - y0)
        pred_dir = np.sign(y_pred - y0)
        correct_directions = np.sum(actual_dir == pred_dir)
        directional_accuracy = float((correct_directions / len(actual_dir)) * 100) if len(actual_dir) > 0 else 0.0

        # Qualitative verdict
        if directional_accuracy >= 65.0 and mape <= 8.0:
            verdict = f"Alta fidelidad predictiva: Acierto direccional del {directional_accuracy:.1f}% con bajo margen de error (MAPE {mape:.1f}%)."
        elif directional_accuracy >= 50.0:
            verdict = f"Fidelidad moderada: Acierto direccional del {directional_accuracy:.1f}% con desviación promedio de {mae:.2f} {data.unit}."
        else:
            verdict = f"Divergencia de régimen: El mercado experimentó shock o cambio de tendencia frente a la inercia proyectada (Acierto {directional_accuracy:.1f}%)."

        # Package historical train window (keep up to 120 points for clean visualization)
        display_train = train_points[-120:]

        return BacktestResponse(
            series_id=series_id.upper(),
            cutoff_date=cutoff_date,
            horizon=eval_horizon,
            historical_dates=[p.timestamp for p in display_train],
            historical_values=[p.value for p in display_train],
            future_actual_dates=[p.timestamp for p in actual_eval_points],
            future_actual_values=[p.value for p in actual_eval_points],
            future_predicted_values=[round(float(v), 2) for v in y_pred],
            future_lower_bound=[round(float(v), 2) for v in forecast_res.lower_bound[:eval_horizon]],
            future_upper_bound=[round(float(v), 2) for v in forecast_res.upper_bound[:eval_horizon]],
            metrics=BacktestMetrics(
                mae=round(mae, 2),
                mape=round(mape, 2),
                directional_accuracy=round(directional_accuracy, 1),
                observations_evaluated=eval_horizon
            ),
            verdict=verdict
        )
