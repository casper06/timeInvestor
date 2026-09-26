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

    #: Static identifier for the active engine, exposed to callers (e.g. /api/health)
    #: that need the real engine name without running a forecast. Subclasses override.
    model_name: str = "base-forecast-engine"

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

    model_name = "damped-holt-mle"

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
            interval_level=confidence,
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


class NotSeasonalError(ValueError):
    """Holt-Winters was asked for a series the seasonality detector (3.0a) does
    not mark as seasonal. Raised instead of silently fitting a seasonal model
    to a series without a cycle, or silently answering with plain Holt."""


class HoltWintersForecastEngine(BaseForecastEngine):
    """
    Holt-Winters: ETS(A,Ad,A) via statsmodels' ETSModel (item 3.0b).

    - On log values when the series is positive: additive seasonality in log is
      multiplicative in levels, consistent with DampedHoltForecastEngine, which
      also works in log.
    - Additive damped trend, as Holt.
    - Parameters by maximum likelihood: ETSModel.fit maximizes the
      log-likelihood (ExponentialSmoothing, the other statsmodels API, minimizes
      SSE instead and has no get_prediction).
    - Seasonal period from backend.services.seasonality.detect_seasonality; only
      series it marks as seasonal are accepted (NotSeasonalError otherwise).
    - Intervals: the library's analytic ones (get_prediction(method="exact")).
      ETS(A,Ad,A) is linear, so they have a closed form; they're deterministic
      (simulated ones depend on the random draw) and Gaussian like Holt's, so a
      comparison between the two isolates the seasonal component. Point value:
      exp(mu + var/2) and bounds exp(mu ± z·se), exactly as Holt does in log.
    """

    def forecast(
        self,
        points: List[TimeSeriesPoint],
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "M",
    ) -> ForecastResponse:
        import warnings as _warnings
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel
        from backend.services.seasonality import detect_seasonality

        sorted_points = sorted(points, key=lambda p: p.timestamp)
        seasonality = detect_seasonality(sorted_points)
        if not seasonality.is_seasonal:
            raise NotSeasonalError(f"Holt-Winters no aplica a esta serie: {seasonality.reason}")
        m = seasonality.period

        vals = np.array([p.value for p in sorted_points], dtype=float)
        use_log = bool(np.all(vals > 0))
        y = np.log(vals) if use_log else vals

        # A pandas Series with a plain integer index: get_prediction needs an
        # index for its row labels; integer positions avoid any date/freq logic.
        import pandas as pd
        model = ETSModel(
            pd.Series(y), error="add", trend="add", damped_trend=True,
            seasonal="add", seasonal_periods=m, initialization_method="estimated",
        )
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            res = model.fit(disp=False)
        convergence_warnings = [str(w.message) for w in caught if "converge" in str(w.message).lower()]
        if convergence_warnings:
            logger.warning(f"Holt-Winters: el ajuste MLE avisó que no convergió: {convergence_warnings[0]}")

        n = len(y)
        pred = res.get_prediction(start=n, end=n + horizon - 1, method="exact")
        frame = pred.summary_frame(alpha=1.0 - confidence)
        mu = np.asarray(frame["mean"], dtype=float)
        lo = np.asarray(frame["pi_lower"], dtype=float)
        hi = np.asarray(frame["pi_upper"], dtype=float)
        z = stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0)
        var = ((hi - lo) / (2.0 * z)) ** 2

        if use_log:
            values = np.exp(mu + var / 2.0)
            lower, upper = np.exp(lo), np.exp(hi)
        else:
            values, lower, upper = mu, lo, hi

        params = dict(zip(res.param_names, np.asarray(res.params, dtype=float)))
        fitted = {
            "alpha": round(params.get("smoothing_level", float("nan")), 4),
            "beta": round(params.get("smoothing_trend", float("nan")), 4),
            "gamma": round(params.get("smoothing_seasonal", float("nan")), 4),
            "phi": round(params.get("damping_trend", float("nan")), 4),
            "seasonal_period": float(m),
            "log_likelihood": round(float(res.llf), 3),
            "converged": 0.0 if convergence_warnings else 1.0,
        }
        timestamps = DampedHoltForecastEngine()._generate_future_timestamps(sorted_points[-1].timestamp, horizon, freq)
        return ForecastResponse(
            timestamps=timestamps,
            values=[round(float(v), 2) for v in values],
            lower_bound=[round(float(v), 2) for v in lower],
            upper_bound=[round(float(v), 2) for v in upper],
            model_name=f"holt-winters-ets(A,Ad,A) m={m}",
            interval_level=confidence,
            fitted_params=fitted,
        )


class TimesFMForecastEngine(BaseForecastEngine):
    """
    Adapter for Google TimesFM 2.5 (200M), the PyTorch foundation model for time series
    forecasting, via the official `timesfm` PyPI package (extra `[torch]`).
    Loads 'google/timesfm-2.5-200m-pytorch' from Hugging Face if enabled.
    Gracefully falls back to DampedHoltForecastEngine when weights or PyTorch are absent.

    Note on checkpoint version: `google/timesfm-1.0-200m-pytorch` (referenced by an
    earlier version of this adapter) is NOT the checkpoint this loads. The `timesfm`
    package on PyPI (versions >=2.0) only ships TimesFM 2.5+; version 1.0.0 of that
    package is JAX-only (requires jax/paxml/praxis, incompatible `backend` values,
    and numpy/pandas pins that conflict with this project's requirements.txt) and
    exposes no `TimesFm` class compatible with a "pytorch" checkpoint at all. TimesFM
    2.5-200M is the closest real, loadable equivalent — same parameter count, same
    Google model family, actively maintained.
    """

    # Context/horizon limits the model was compiled for. 512 matches this project's
    # existing context window elsewhere (DampedHoltForecastEngine, benchmark script);
    # 128 is the largest horizon this project currently requests (see ForecastRequest.horizon,
    # capped at 365 by the schema but the UI never asks past ~180 in practice) rounded up
    # to a multiple of the model's output patch size (see compile()'s own rounding logic).
    MAX_CONTEXT = 512
    MAX_HORIZON = 128
    # The band: the widest the quantile head offers (p10-p90 -> 80% nominal).
    BAND_LOW_Q = 0.1
    BAND_HIGH_Q = 0.9

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

    @classmethod
    def is_available(cls) -> bool:
        """Whether real TimesFM weights are loaded in this process, cheap enough to
        ask on every request.

        With USE_REAL_TIMESFM=false it never touches the singleton. Otherwise the
        first call per process does the one-time load that any TimesFM use does
        anyway; every later call only reads `_model`, because __init__ marks the
        singleton initialized before loading and never retries a failed load.
        Caching it per process is exact: installing the package, downloading the
        weights or flipping USE_REAL_TIMESFM all require a restart.
        """
        if not settings.USE_REAL_TIMESFM:
            return False
        return cls()._model is not None

    def _quantile_columns(self, n_columns: int) -> tuple:
        """(p10 column, p90 column) in quantile_forecast, looked up BY VALUE in
        the loaded model's config.quantiles (column 0 is the mean). Raises if
        the output doesn't have the expected [mean, *quantiles] layout, which
        forecast() turns into an explicit fallback, never a mislabeled band."""
        quantiles = list(getattr(getattr(self._model, "model", None), "config", None).quantiles)
        if n_columns != len(quantiles) + 1:
            raise ValueError(
                f"Formato de cuantiles inesperado: {n_columns} columnas para {len(quantiles)} cuantiles "
                f"(se esperaba [media, *cuantiles])"
            )

        def column(q: float) -> int:
            for i, value in enumerate(quantiles):
                if abs(value - q) < 1e-9:
                    return 1 + i
            raise ValueError(f"El modelo no tiene el cuantil {q} (tiene {quantiles})")

        return column(self.BAND_LOW_Q), column(self.BAND_HIGH_Q)

    @property
    def model_name(self) -> str:
        """Reflects which engine is actually active: real TimesFM weights, or the Damped Holt fallback."""
        if self._model is not None:
            return f"timesfm-2.5-200m ({self.device})"
        return "damped-holt-mle (fallback: TimesFM no disponible)"

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
        logger.info(f"Attempting to load Google TimesFM 2.5 (200M) model onto {self.device}...")
        try:
            import timesfm

            model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                "google/timesfm-2.5-200m-pytorch"
            )
            model.model.to(self.device)
            model.compile(
                timesfm.ForecastConfig(
                    max_context=self.MAX_CONTEXT,
                    max_horizon=self.MAX_HORIZON,
                    normalize_inputs=True,
                    use_continuous_quantile_head=True,
                    force_flip_invariance=True,
                    infer_is_positive=True,
                    fix_quantile_crossing=True,
                )
            )
            self._model = model
            logger.info("Successfully loaded Google TimesFM 2.5 (200M) PyTorch weights.")
        except Exception as e:
            # Logged with full detail (not swallowed) so a load failure is diagnosable
            # from the server log instead of silently falling back with no trace.
            logger.warning(
                f"Could not load TimesFM 2.5 PyTorch weights ({e}). "
                "Ensure 'timesfm[torch]', 'torch', and 'transformers' are installed and "
                "the Hugging Face repo 'google/timesfm-2.5-200m-pytorch' is reachable "
                "(or already cached locally). Will use DampedHoltForecastEngine.",
                exc_info=True,
            )
            self._model = None

    def forecast(
        self,
        points: List[TimeSeriesPoint],
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D"
    ) -> ForecastResponse:
        # Why TimesFM didn't run, when it doesn't: the caller needs the cause to
        # tell the user whether waiting helps (see fallback_kind in the schema).
        fallback_kind, fallback_reason = None, None
        if self._model is None:
            fallback_kind = "not_loaded"
            fallback_reason = (
                "TimesFM no está cargado en el servidor (paquete o pesos sin instalar, "
                "o USE_REAL_TIMESFM=false)."
            )
        elif horizon > self.MAX_HORIZON:
            fallback_kind = "horizon_exceeded"
            fallback_reason = (
                f"El horizonte pedido ({horizon}) supera el máximo compilado de TimesFM "
                f"({self.MAX_HORIZON})."
            )
            logger.warning(f"TimesFM: {fallback_reason} Usando Holt.")
        else:
            try:
                context_vals = np.array([p.value for p in points[-self.MAX_CONTEXT:]], dtype=np.float64)

                point_forecast, quantile_forecast = self._model.forecast(
                    horizon=horizon,
                    inputs=[context_vals],
                )

                pred_values = [round(float(v), 2) for v in point_forecast[0][:horizon]]

                # The model's quantile head only exposes deciles (p10..p90), not a
                # genuine 95% interval. Reporting p10/p90 AS 95% would fabricate a
                # coverage level the model never produced, so the band is p10-p90
                # and it's declared as 80% (interval_level), whatever was requested.
                # Columns are found BY VALUE in the model's config: TimesFM 2.5
                # returns [mean, q_1, ..., q_n] with q = config.quantiles, so
                # column 0 is the mean, not p10 (reading it as p10 made the band
                # [mean, p90] until 2026-09-26).
                if quantile_forecast is not None and quantile_forecast.shape[-1] >= 2:
                    lo_col, hi_col = self._quantile_columns(quantile_forecast.shape[-1])
                    lower_b = [round(float(v), 2) for v in quantile_forecast[0, :horizon, lo_col]]
                    upper_b = [round(float(v), 2) for v in quantile_forecast[0, :horizon, hi_col]]
                    reported_interval_pct = round((self.BAND_HIGH_Q - self.BAND_LOW_Q) * 100.0, 1)
                else:
                    # No quantile head available at all — approximate from recent
                    # realized volatility, same spirit as the historical fallback
                    # this replaces, and label it honestly as approximate.
                    spread = np.std(context_vals[-30:]) * np.sqrt(np.arange(1, horizon + 1)) * 0.5
                    lower_b = [round(float(p - s), 2) for p, s in zip(pred_values, spread)]
                    upper_b = [round(float(p + s), 2) for p, s in zip(pred_values, spread)]
                    reported_interval_pct = None

                last_ts = points[-1].timestamp
                future_timestamps = self._fallback_engine._generate_future_timestamps(last_ts, horizon, freq)

                fitted_params = None
                if reported_interval_pct is not None:
                    fitted_params = {
                        "requested_confidence_pct": round(confidence * 100.0, 1),
                        "actual_interval_pct": reported_interval_pct,
                    }

                return ForecastResponse(
                    timestamps=future_timestamps,
                    values=pred_values,
                    lower_bound=lower_b,
                    upper_bound=upper_b,
                    model_name=f"timesfm-2.5-200m ({self.device})",
                    is_fallback=False,
                    interval_level=(reported_interval_pct / 100.0) if reported_interval_pct is not None else None,
                    fitted_params=fitted_params,
                )

            except Exception as e:
                logger.error(f"Error during real TimesFM inference: {e}. Reverting to fallback.", exc_info=True)
                fallback_kind = "inference_error"
                fallback_reason = f"La inferencia de TimesFM falló: {type(e).__name__}: {e}"

        # Transparent fallback to Damped Holt
        res = self._fallback_engine.forecast(points, horizon, confidence, freq)
        res.model_name = "damped-holt-mle (fallback: TimesFM no disponible)"
        res.is_fallback = True
        res.fallback_kind = fallback_kind
        res.fallback_reason = fallback_reason
        return res


def get_forecast_engine(engine_type: Optional[str] = None) -> BaseForecastEngine:
    """Factory to retrieve configured forecasting engine."""
    eng = (engine_type or settings.FORECAST_ENGINE).lower()

    if settings.USE_REAL_TIMESFM or eng == "timesfm":
        return TimesFMForecastEngine()
    else:
        return DampedHoltForecastEngine()
