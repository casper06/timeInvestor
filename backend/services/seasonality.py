"""
Seasonality detection and the seasonal naive benchmark (item 3.0a).

Until this existed nothing in the backtest was seasonal: the only benchmark was
the random walk and MASE was scaled by the 1-step naive. For a monthly series
with an annual cycle that's a weak baseline: "same month last year" (the
seasonal naive) is the rival any model has to beat there.

When is a series seasonal? Never inferred from its name. Two conditions, both
computed on the training data only (no look-ahead):

1. Frequency, from the median gap between timestamps. Monthly -> period m=12,
   quarterly -> m=4. Daily and weekly series are not tested for an annual
   cycle (m would be ~252 or 52, needing many years of data for a meaningful
   test); they're reported as "not evaluated", never as "not seasonal".
2. An autocorrelation test at lag m: the seasonality test of the M4
   competition's Theta benchmark (Assimakopoulos & Nikolopoulos),
   ACF(m) > 1.645 * sqrt((1 + 2 * sum_{k<m} ACF(k)^2) / n)  (Bartlett variance,
   90% one-sided). Two deliberate differences from M4:
   - it runs on first differences (of the log when the series is positive),
     not on levels: any trending series has a high ACF at every lag, so on
     levels a plain trend (e.g. INDPRO) would pass as seasonal;
   - it is one-sided positive (M4 uses |ACF(m)|): the seasonal naive only
     helps if the same period last year is positively related to this one.
   It needs at least 3*m differences.
"""
import math
from datetime import date
from typing import List, Optional, Sequence

import numpy as np

from backend.schemas.models import SeasonalityInfo, TimeSeriesPoint

SEASONAL_PERIODS = {"monthly": 12, "quarterly": 4}
ACF_CRITICAL = 1.645  # 90% one-sided, as in the M4 Theta benchmark's test
MIN_CYCLES = 3


def infer_frequency(timestamps: Sequence[str]) -> str:
    """'daily' | 'weekly' | 'monthly' | 'quarterly' | 'annual' | 'irregular',
    from the median gap in days between consecutive observations."""
    if len(timestamps) < 3:
        return "irregular"
    days = sorted(date.fromisoformat(t[:10]).toordinal() for t in timestamps)
    gap = float(np.median(np.diff(days)))
    if gap <= 4:
        return "daily"  # includes business-day series (Mon->Fri gaps of 1 and 3)
    if 5 <= gap <= 10:
        return "weekly"
    if 25 <= gap <= 35:
        return "monthly"
    if 80 <= gap <= 100:
        return "quarterly"
    if 350 <= gap <= 380:
        return "annual"
    return "irregular"


def _acf(x: np.ndarray, max_lag: int) -> np.ndarray:
    """Sample autocorrelation for lags 0..max_lag (standard biased estimator)."""
    x = x - x.mean()
    denom = float(np.dot(x, x))
    return np.array([float(np.dot(x[: len(x) - k], x[k:])) / denom for k in range(max_lag + 1)])


def detect_seasonality(points: List[TimeSeriesPoint]) -> SeasonalityInfo:
    """Seasonality verdict for a series, with the numbers behind it."""
    ordered = sorted(points, key=lambda p: p.timestamp)
    frequency = infer_frequency([p.timestamp for p in ordered])
    m = SEASONAL_PERIODS.get(frequency)
    if m is None:
        return SeasonalityInfo(
            frequency=frequency, period=None, is_seasonal=False, n_obs=len(ordered),
            reason=(f"Frecuencia {frequency}: la estacionalidad anual solo se evalúa en series "
                    f"mensuales (m=12) o trimestrales (m=4). No evaluada."),
        )

    vals = np.array([p.value for p in ordered], dtype=float)
    x = np.diff(np.log(vals)) if np.all(vals > 0) else np.diff(vals)
    n = len(x)
    if n < MIN_CYCLES * m:
        return SeasonalityInfo(
            frequency=frequency, period=m, is_seasonal=False, n_obs=len(ordered),
            reason=f"Historia insuficiente para el test ({n} diferencias < {MIN_CYCLES}×{m}). No evaluada.",
        )
    if float(np.var(x)) == 0.0:
        return SeasonalityInfo(
            frequency=frequency, period=m, is_seasonal=False, n_obs=len(ordered),
            reason="Serie sin variación en las diferencias: no hay estacionalidad que medir.",
        )

    acf = _acf(x, m)
    threshold = ACF_CRITICAL * math.sqrt((1.0 + 2.0 * float(np.sum(acf[1:m] ** 2))) / n)
    is_seasonal = bool(acf[m] > threshold)
    verdict = "estacional" if is_seasonal else "sin estacionalidad detectada"
    return SeasonalityInfo(
        frequency=frequency, period=m, is_seasonal=is_seasonal, n_obs=len(ordered),
        acf_at_period=round(float(acf[m]), 4), threshold=round(threshold, 4),
        reason=(f"ACF de las diferencias en el lag {m} = {acf[m]:.3f} "
                f"{'>' if is_seasonal else '≤'} umbral {threshold:.3f}: {verdict}."),
    )


def seasonal_naive_forecast(train_values: Sequence[float], horizon: int, m: int) -> np.ndarray:
    """y_hat[T+h] = y[T+h-m*ceil(h/m)]: the last observed season, repeated."""
    last_season = np.asarray(train_values[-m:], dtype=float)
    return np.array([last_season[(h - 1) % m] for h in range(1, horizon + 1)])


def seasonal_scale(train_values: Sequence[float], m: int) -> Optional[float]:
    """In-sample MAE of the seasonal naive, mean |y_t - y_{t-m}|: the scale of
    the seasonally scaled MASE. None if the training set is shorter than m+1."""
    y = np.asarray(train_values, dtype=float)
    if len(y) <= m:
        return None
    return float(np.mean(np.abs(y[m:] - y[:-m])))
