import abc
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import numpy as np
from scipy import stats, optimize

from backend.config import settings
from backend.schemas.models import TimeSeriesPoint, ForecastResponse

logger = logging.getLogger(__name__)

class BaseForecastEngine(abc.ABC):
    """Abstract interface for Time Series Forecasting engines (Google TimesFM contract)."""

    @abc.abstractmethod
    def forecast(
        self,
        points: List[TimeSeriesPoint],
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D"
    ) -> ForecastResponse:
        """Generates future projections with upper and lower prediction bounds."""
        pass


class DampedHoltForecastEngine(BaseForecastEngine):
    """
    Production-grade statistical engine implementing Damped Holt exponential smoothing.
    Parameters (alpha, beta, phi) are estimated via Maximum Likelihood / SSE optimization.
    Variance of forecast error is calculated analytically following Hyndman & Athanasopoulos
    (Forecasting: Principles and Practice).
    Models on log-prices with log-normal bias correction for point estimates.
    """

    def forecast(
        self,
        points: List[TimeSeriesPoint],
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D"
    ) -> ForecastResponse:
        if len(points) < 2:
            raise ValueError("At least 2 points are required for time series forecasting")

        # Sort points by timestamp
        sorted_points = sorted(points, key=lambda p: p.timestamp)
        vals = np.array([p.value for p in sorted_points], dtype=float)
        n = len(vals)

        # Decide whether to use log transformation (prices > 0)
        use_log = np.all(vals > 0)
        y = np.log(vals) if use_log else vals.copy()

        # Fit Holt's damped trend exponential smoothing via SSE minimization
        def sse_loss(params):
            alpha, beta, phi = params
            level = y[0]
            trend = (y[1] - y[0]) if n > 1 else 0.0
            sse = 0.0
            for t in range(1, n):
                y_hat = level + phi * trend
                e = y[t] - y_hat
                sse += e * e
                level = y_hat + alpha * e
                trend = phi * trend + alpha * beta * e
            return sse

        init = [0.3, 0.1, 0.95]
        bounds = [(0.01, 0.99), (0.01, 0.99), (0.80, 0.98)]
        try:
            opt_res = optimize.minimize(sse_loss, init, method="L-BFGS-B", bounds=bounds)
            alpha, beta, phi = opt_res.x
        except Exception as opt_err:
            logger.warning(f"Optimization failed: {opt_err}, falling back to default parameters")
            alpha, beta, phi = 0.3, 0.1, 0.95

        # Re-run filter with fitted parameters to obtain final state and residual variance
        level = y[0]
        trend = (y[1] - y[0]) if n > 1 else 0.0
        residuals = []

        for t in range(1, n):
            y_hat = level + phi * trend
            e = y[t] - y_hat
            residuals.append(e)
            level = y_hat + alpha * e
            trend = phi * trend + alpha * beta * e

        sigma2 = float(np.mean(np.square(residuals))) if len(residuals) > 1 else 1e-4
        if sigma2 <= 0 or np.isnan(sigma2):
            sigma2 = 1e-4
        sigma = np.sqrt(sigma2)

        # Confidence z-score (two-tailed)
        alpha_conf = 1.0 - confidence
        z = stats.norm.ppf(1.0 - alpha_conf / 2.0)

        # Analytical variance of forecast error for additive Damped Holt:
        # Var(y_hat_{T+h}) = sigma^2 * [ 1 + sum_{j=1}^{h-1} (alpha + alpha*beta*phi*(1 - phi^j)/(1 - phi))^2 ]
        future_vals = []
        lower_bounds = []
        upper_bounds = []

        c_sum = 0.0
        allow_negative = np.any(vals < 0)

        for h in range(1, horizon + 1):
            if abs(1.0 - phi) > 1e-7:
                cum_phi = phi * (1.0 - phi**h) / (1.0 - phi)
            else:
                cum_phi = float(h)
            y_hat_h = level + cum_phi * trend

            if h == 1:
                var_h = sigma2
            else:
                j = h - 1
                if abs(1.0 - phi) > 1e-7:
                    c_j = alpha + alpha * beta * phi * (1.0 - phi**j) / (1.0 - phi)
                else:
                    c_j = alpha + alpha * beta * j
                c_sum += c_j * c_j
                var_h = sigma2 * (1.0 + c_sum)

            se_h = np.sqrt(var_h)

            if use_log:
                # Log-normal bias correction for point forecast: exp(mu + var/2)
                pred_val = float(np.exp(y_hat_h + var_h / 2.0))
                lb = float(np.exp(y_hat_h - z * se_h))
                ub = float(np.exp(y_hat_h + z * se_h))
            else:
                pred_val = float(y_hat_h)
                lb = float(y_hat_h - z * se_h)
                ub = float(y_hat_h + z * se_h)
                if not allow_negative:
                    lb = max(0.0, lb)

            future_vals.append(round(pred_val, 2))
            lower_bounds.append(round(lb, 2))
            upper_bounds.append(round(ub, 2))

        # Extrapolate timestamps
        last_ts_str = sorted_points[-1].timestamp
        future_timestamps = self._generate_future_timestamps(last_ts_str, horizon, freq)

        return ForecastResponse(
            timestamps=future_timestamps,
            values=future_vals,
            lower_bound=lower_bounds,
            upper_bound=upper_bounds,
            model_name="damped-holt-mle",
            is_fallback=False,
            fitted_params={
                "alpha": round(float(alpha), 4),
                "beta": round(float(beta), 4),
                "phi": round(float(phi), 4),
                "sigma": round(float(sigma), 4)
            }
        )

    def _generate_future_timestamps(self, last_ts: str, horizon: int, freq: str) -> List[str]:
        """Generates consecutive future timestamps starting from the day/month after last_ts."""
        try:
            if len(last_ts) >= 10:
                dt = datetime.strptime(last_ts[:10], "%Y-%m-%d")
            else:
                dt = datetime.now()
        except ValueError:
            dt = datetime.now()

        res: List[str] = []
        cur = dt
        
        if freq.upper() == "M":
            for _ in range(horizon):
                month = cur.month + 1
                year = cur.year
                if month > 12:
                    month = 1
                    year += 1
                cur = datetime(year, month, min(cur.day, 28))
                res.append(cur.strftime("%Y-%m-%d"))
        elif freq.upper() == "W":
            for _ in range(horizon):
                cur += timedelta(days=7)
                res.append(cur.strftime("%Y-%m-%d"))
        else:
            added = 0
            while added < horizon:
                cur += timedelta(days=1)
                if cur.weekday() < 5:
                    res.append(cur.strftime("%Y-%m-%d"))
                    added += 1

        return res


# Backward compatibility alias
StatisticalMockForecastEngine = DampedHoltForecastEngine


class TimesFMForecastEngine(BaseForecastEngine):
    """
    Adapter for Google TimesFM (PyTorch foundation model for time series).
    Loads 'google/timesfm-1.0-200m-pytorch' from Hugging Face if enabled.
    Gracefully falls back to DampedHoltForecastEngine when weights or PyTorch are absent.
    """

    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TimesFMForecastEngine, cls).__new__(cls)
            cls._instance._fallback_engine = DampedHoltForecastEngine()
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.device = self._detect_device()

        if settings.USE_REAL_TIMESFM:
            self._load_model()
        else:
            logger.info("TimesFM PyTorch engine disabled via USE_REAL_TIMESFM=false. Using DampedHoltForecastEngine.")

    def _detect_device(self) -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
            else:
                return "cpu"
        except ImportError:
            return "cpu"

    def _load_model(self):
        logger.info(f"Attempting to load Google TimesFM 200M model onto {self.device}...")
        try:
            import timesfm
            self._model = timesfm.TimesFm(
                context_len=512,
                horizon_len=128,
                input_patch_len=32,
                output_patch_len=128,
                num_layers=20,
                model_dims=1280,
                backend=self.device
            )
            self._model.load_from_checkpoint(repo_id="google/timesfm-1.0-200m-pytorch")
            logger.info("Successfully loaded Google TimesFM PyTorch weights.")
        except Exception as e:
            logger.warning(
                f"Could not load TimesFM PyTorch weights ({e}). "
                "Ensure 'timesfm', 'torch', and 'transformers' are installed and HF is accessible. "
                "Will use DampedHoltForecastEngine."
            )
            self._model = None

    def forecast(
        self,
        points: List[TimeSeriesPoint],
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D"
    ) -> ForecastResponse:
        freq_map = {"D": 0, "W": 1, "M": 2}
        freq_code = freq_map.get(freq.upper(), 0)

        if self._model is not None:
            try:
                context_vals = [p.value for p in points[-512:]]
                
                point_forecast, experimental_quantile_forecast = self._model.forecast(
                    inputs=[context_vals],
                    freq=[freq_code]
                )

                pred_values = [round(float(v), 2) for v in point_forecast[0][:horizon]]
                
                if experimental_quantile_forecast is not None and len(experimental_quantile_forecast[0]) >= 2:
                    lower_b = [round(float(v), 2) for v in experimental_quantile_forecast[0][0][:horizon]]
                    upper_b = [round(float(v), 2) for v in experimental_quantile_forecast[0][-1][:horizon]]
                else:
                    spread = np.std(context_vals[-30:]) * np.sqrt(np.arange(1, horizon + 1)) * 0.5
                    lower_b = [round(float(p - s), 2) for p, s in zip(pred_values, spread)]
                    upper_b = [round(float(p + s), 2) for p, s in zip(pred_values, spread)]

                last_ts = points[-1].timestamp
                future_timestamps = self._fallback_engine._generate_future_timestamps(last_ts, horizon, freq)

                return ForecastResponse(
                    timestamps=future_timestamps,
                    values=pred_values,
                    lower_bound=lower_b,
                    upper_bound=upper_b,
                    model_name=f"google-timesfm-200m ({self.device})",
                    is_fallback=False
                )

            except Exception as e:
                logger.error(f"Error during real TimesFM inference: {e}. Reverting to fallback.", exc_info=True)

        # Transparent fallback to Damped Holt
        res = self._fallback_engine.forecast(points, horizon, confidence, freq)
        res.model_name = "damped-holt-mle (fallback: TimesFM no disponible)"
        res.is_fallback = True
        return res


def get_forecast_engine(engine_type: Optional[str] = None) -> BaseForecastEngine:
    """Factory to retrieve configured forecasting engine."""
    eng = (engine_type or settings.FORECAST_ENGINE).lower()

    if settings.USE_REAL_TIMESFM or eng == "timesfm":
        return TimesFMForecastEngine()
    else:
        return DampedHoltForecastEngine()
