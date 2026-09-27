"""
"No confiable" mark for forecasts (item 2.6 of docs/PLAN.md).

A forecast is marked unreliable when, at the end of the horizon, it moves the
series more than FLAG_X times the largest move the series ever made in that
many steps in its own history (in log terms for positive series). Damped Holt
can do this when the last observation is a level jump: the fit hands the jump
to the trend and extrapolates it (UNRATE cut at 2020-04: 20,855% at 12
months; docs/results/holt_explosion_2026-09-27.md).

The mark never changes a number: the forecast is shown as it came out, with
the warning (CONTEXT.md, rule 6). It applies to any engine.
"""
from typing import Optional, Sequence

import numpy as np

# Pre-registered in the 2.6 round log before measuring its false positives.
FLAG_X = 2.0


def max_historical_move(values: Sequence[float], h: int, use_log: bool) -> float:
    """Largest |log(y_{t+h}/y_t)| (or |y_{t+h} - y_t|) in `values`; over the
    longest span available if the history is shorter than h."""
    v = np.asarray(values, dtype=float)
    h = min(h, len(v) - 1)
    if h < 1:
        return 0.0
    a, b = v[:-h], v[h:]
    moves = np.abs(np.log(b / a)) if use_log else np.abs(b - a)
    return float(moves.max())


def explosion_index(history: Sequence[float], forecast_end: float, h: int) -> Optional[float]:
    """|move of the forecast over h steps| / largest h-step move in history.
    None when the history never moved (nothing to compare with)."""
    use_log = bool(np.all(np.asarray(history, dtype=float) > 0) and forecast_end > 0)
    m = max_historical_move(history, h, use_log)
    if m <= 0:
        return None
    last = float(history[-1])
    move = abs(np.log(forecast_end / last)) if use_log else abs(forecast_end - last)
    return float(move / m)


def reliability_warning(history: Sequence[float], forecast_values: Sequence[float],
                        horizon_label: str) -> Optional[str]:
    """Warning text if the forecast is implausible (X > FLAG_X), else None."""
    if len(history) < 3 or not forecast_values:
        return None
    end = float(forecast_values[-1])
    x = explosion_index(history, end, len(forecast_values))
    if x is None or x <= FLAG_X:
        return None
    last = float(history[-1])
    ratio = f" (×{end / last:,.1f} el último valor)" if last > 0 and end > 0 else ""
    return (
        f"Pronóstico no confiable: a {horizon_label} proyecta {end:,.2f}{ratio}, un movimiento "
        f"{x:.1f} veces mayor que el máximo que la serie tuvo en {horizon_label} en toda su historia. "
        f"Suele pasar cuando el último dato es un salto de nivel y el motor lo extrapola como tendencia. "
        f"Los números se muestran tal como salieron, sin recortar."
    )
