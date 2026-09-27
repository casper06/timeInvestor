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
from backend.services.horizons import format_horizon, resolve_frequency
from backend.services.reliability import reliability_warning
from backend.services.seasonality import detect_seasonality, seasonal_naive_forecast, seasonal_scale

logger = logging.getLogger(__name__)

# A scale this small relative to the series' level is numerically zero: the
# metric it divides is not defined (2.10). Never replaced by + epsilon.
NEGLIGIBLE_SCALE = 1e-9

WHY_MASE = "MASE no definido: la serie no varió en el período de entrenamiento (el error del naive a un paso es 0)"
WHY_MASE_SEASONAL = ("MASE estacional no definido: en el entrenamiento la serie repitió exactamente el ciclo "
                     "anterior (el error del naive estacional es 0)")
WHY_MAPE = "MAPE no definido: algún valor real del período evaluado es 0"


def _is_negligible(scale: float, level: float) -> bool:
    return scale <= NEGLIGIBLE_SCALE * max(1.0, abs(level))


def _scaled(num: float, scale: float, level: float):
    """num / scale, or None when the scale is (numerically) zero."""
    return None if _is_negligible(scale, level) else float(num / scale)


def _mape(actual, pred, level: float):
    """MAPE (%), or None when some actual value is (numerically) zero."""
    if np.any(np.abs(actual) <= NEGLIGIBLE_SCALE * max(1.0, abs(level))):
        return None
    return float(np.mean(np.abs((actual - pred) / np.abs(actual))) * 100)


def _r(x, nd):
    """Kept as a no-op pass-through: metrics are returned at full precision
    (2.11); they are rounded only when displayed. `nd` documents the
    precision the UI shows."""
    return None if x is None else float(x)


def _mase_s_text(x):
    return "MASE estacional no definido" if x is None else f"MASE estacional {x:.3f}"

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
        # From the dates, not the series type: FRED has daily series (DGS10).
        # The type is only the fallback when the dates can't tell.
        frequency, freq = resolve_frequency([p.timestamp for p in sorted_points], "M" if data.type == "macro" else "D")
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

        # MAPE with absolute denominator (negative series are fine); not
        # defined if some actual value is 0 (2.10).
        epsilon = 1e-8  # only for sMAPE, where it can only turn 0/0 into 0
        y_train_vals = np.array([p.value for p in train_points], dtype=float)
        level = float(np.mean(np.abs(y_train_vals))) if len(y_train_vals) else 1.0
        mape = _mape(y_actual, y_pred, level)
        undefined = {}
        if mape is None:
            undefined["mape"] = WHY_MAPE

        # sMAPE: Symmetric Mean Absolute Percentage Error
        smape = float(np.mean(2.0 * np.abs(y_actual - y_pred) / (np.abs(y_actual) + np.abs(y_pred) + epsilon)) * 100)

        # MASE: Mean Absolute Scaled Error relative to in-sample 1-step naive
        # forecast. Not defined when that scale is 0 (a series that didn't
        # move in training, e.g. a policy rate between moves): None + reason.
        in_sample_naive_mae = float(np.mean(np.abs(np.diff(y_train_vals)))) if len(y_train_vals) > 1 else 0.0
        mase = _scaled(mae, in_sample_naive_mae, level)
        if mase is None:
            undefined["mase"] = WHY_MASE

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
        naive_mape = _mape(y_actual, y_naive, level)
        naive_smape = float(np.mean(2.0 * np.abs(y_actual - y_naive) / (np.abs(y_actual) + np.abs(y_naive) + epsilon)) * 100)
        naive_mase = _scaled(naive_mae, in_sample_naive_mae, level)

        naive_metrics = BacktestMetrics(
            mae=float(naive_mae),
            mape=_r(naive_mape, 2),
            smape=float(naive_smape),
            mase=_r(naive_mase, 3),
            directional_accuracy=0.0,
            observations_evaluated=eval_horizon,
            undefined=dict(undefined),
        )

        # 5b. Seasonal naive benchmark + seasonally scaled MASE, only for series
        # whose TRAINING data passes the seasonality test (no look-ahead). The
        # 1-step `mase` above stays as it is; the seasonal one goes in its own
        # field, for the model and for both naive benchmarks.
        seasonality = detect_seasonality(train_points)
        seasonal_naive_metrics = None
        mase_seasonal = None
        s_scale = seasonal_scale(y_train_vals, seasonality.period) if seasonality.is_seasonal else None
        if s_scale is not None:
            m = seasonality.period
            y_snaive = seasonal_naive_forecast(y_train_vals, eval_horizon, m)
            snaive_mae = float(np.mean(np.abs(y_actual - y_snaive)))
            if eval_horizon > 1:
                snaive_dir = float(np.mean(np.sign(np.diff(y_actual)) == np.sign(np.diff(y_snaive))) * 100)
            else:
                snaive_dir = 50.0
            mase_seasonal = _scaled(mae, s_scale, level)
            if mase_seasonal is None:
                undefined["mase_seasonal"] = WHY_MASE_SEASONAL
                naive_metrics.undefined["mase_seasonal"] = WHY_MASE_SEASONAL
            naive_metrics.mase_seasonal = _r(_scaled(naive_mae, s_scale, level), 3)
            snaive_mape = _mape(y_actual, y_snaive, level)
            snaive_undefined = dict(undefined)
            if snaive_mape is None:
                snaive_undefined["mape"] = WHY_MAPE
            seasonal_naive_metrics = BacktestMetrics(
                mae=float(snaive_mae),
                mape=_r(snaive_mape, 2),
                smape=float(np.mean(2.0 * np.abs(y_actual - y_snaive) / (np.abs(y_actual) + np.abs(y_snaive) + epsilon)) * 100),
                mase=_r(_scaled(snaive_mae, in_sample_naive_mae, level), 3),
                mase_seasonal=_r(_scaled(snaive_mae, s_scale, level), 3),
                directional_accuracy=float(snaive_dir),
                observations_evaluated=eval_horizon,
                undefined=snaive_undefined,
            )

        # 6. Verdict and Warnings
        warnings: List[str] = []
        # TimesFMForecastEngine.forecast() catches its own failures and answers
        # with Holt (is_fallback=True). Without surfacing that here, these
        # metrics would be reported as the requested engine's. It goes in the
        # structured is_fallback/fallback_kind/fallback_reason fields (the UI
        # builds its notice from them), not duplicated into `warnings`.
        is_fallback = bool(forecast_res.is_fallback)
        # Coverage is judged against the level the engine ACTUALLY delivered
        # (TimesFM only has an 80% band even if 95% was requested).
        interval_level = forecast_res.interval_level if forecast_res.interval_level is not None else confidence
        nominal_coverage = interval_level * 100.0
        # Implausible forecast (2.6): said, never corrected.
        unreliable = reliability_warning([p.value for p in train_points], forecast_res.values[:eval_horizon],
                                         format_horizon(eval_horizon, frequency))
        if unreliable:
            warnings.append(unreliable)
        if interval_coverage < (nominal_coverage - 15.0):
            warnings.append(
                f"Subcobertura del intervalo: La cobertura empírica observada ({interval_coverage:.1f}%) "
                f"está sustancialmente por debajo del nivel nominal del intervalo ({nominal_coverage:.0f}%)."
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

        if seasonal_naive_metrics is not None:
            snaive_mae = seasonal_naive_metrics.mae
            if mae < snaive_mae:
                verdict += (
                    f" Serie estacional (m={seasonality.period}): frente al naive estacional (mismo período "
                    f"del ciclo anterior) el modelo también gana, reduciendo el MAE un "
                    f"{(snaive_mae - mae) / (snaive_mae + epsilon) * 100:.1f}% "
                    f"({_mase_s_text(mase_seasonal)})."
                )
            else:
                verdict += (
                    f" Serie estacional (m={seasonality.period}): el modelo NO supera al naive estacional "
                    f"(MAE {mae:.2f} vs {snaive_mae:.2f} {data.unit}; {_mase_s_text(mase_seasonal)}). "
                    f"Repetir el mismo período del ciclo anterior predice mejor."
                )

        display_train = train_points[-120:]

        return BacktestResponse(
            series_id=clean_id,
            cutoff_date=cutoff_date,
            horizon=eval_horizon,
            frequency=frequency,
            historical_dates=[p.timestamp for p in display_train],
            historical_values=[p.value for p in display_train],
            future_actual_dates=[p.timestamp for p in actual_eval_points],
            future_actual_values=[p.value for p in actual_eval_points],
            future_predicted_values=[float(v) for v in y_pred],
            future_lower_bound=[float(v) for v in lbs],
            future_upper_bound=[float(v) for v in ubs],
            metrics=BacktestMetrics(
                mae=float(mae),
                mape=_r(mape, 2),
                smape=float(smape),
                mase=_r(mase, 3),
                mase_seasonal=_r(mase_seasonal, 3),
                directional_accuracy=float(directional_accuracy),
                observations_evaluated=eval_horizon,
                undefined=undefined,
            ),
            naive_metrics=naive_metrics,
            seasonal_naive_metrics=seasonal_naive_metrics,
            seasonality=seasonality,
            interval_coverage=float(interval_coverage),
            aggregate_direction_correct=aggregate_direction_correct,
            verdict=verdict,
            warnings=warnings,
            reliable=unreliable is None,
            reliability_warning=unreliable,
            model_name=forecast_res.model_name,
            interval_level=forecast_res.interval_level,
            is_fallback=is_fallback,
            fallback_kind=forecast_res.fallback_kind,
            fallback_reason=forecast_res.fallback_reason,
        )
