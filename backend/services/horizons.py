"""
Forecast horizons in the series' own unit (item 4.14 of docs/PLAN.md).

A horizon is a number of STEPS of the series: 12 on a monthly series is 12
months, 60 on a daily one is 60 business days (the engines generate business
days for daily series). The frequency comes from the dates
(seasonality.infer_frequency), never from the series type or name — FRED has
daily series too (DGS10).

Mirrored in frontend/src/utils/horizon.ts (options, canonical horizon and
labels): keep both in sync.
"""
from typing import Optional, Sequence

from backend.services.seasonality import infer_frequency

# Engine `freq` code per inferred frequency (forecast_engine._generate_future_timestamps).
FREQ_CODE = {"daily": "D", "weekly": "W", "monthly": "M", "quarterly": "Q", "annual": "A"}

# Horizons offered in the UI, and the canonical one (the UI default).
HORIZON_OPTIONS = {
    "daily": [30, 60, 90, 180],
    "weekly": [4, 13, 26],
    "monthly": [3, 6, 12, 24],
    "quarterly": [2, 4, 8],
    "annual": [1, 2, 3],
}
CANONICAL_HORIZON = {"daily": 60, "weekly": 13, "monthly": 12, "quarterly": 4, "annual": 2}

_UNITS = {
    "daily": ("día hábil", "días hábiles"),
    "weekly": ("semana", "semanas"),
    "monthly": ("mes", "meses"),
    "quarterly": ("trimestre", "trimestres"),
    "annual": ("año", "años"),
}


def series_frequency(timestamps: Sequence[str]) -> str:
    """Inferred frequency; 'irregular' (or too few points) is treated as daily,
    which is what the app assumed for every series before 4.14."""
    f = infer_frequency(timestamps)
    return f if f in FREQ_CODE else "daily"


def resolve_frequency(timestamps: Sequence[str], freq_hint: Optional[str] = None) -> tuple:
    """(frequency, engine freq code). The dates decide; `freq_hint` ('D', 'M',
    ...) is used only when they can't (irregular or < 3 points)."""
    inferred = infer_frequency(timestamps)
    if inferred in FREQ_CODE:
        return inferred, FREQ_CODE[inferred]
    by_code = {code: name for name, code in FREQ_CODE.items()}
    code = (freq_hint or "D").upper()
    return (by_code[code], code) if code in by_code else ("daily", "D")


def canonical_horizon(frequency: str) -> int:
    return CANONICAL_HORIZON.get(frequency, CANONICAL_HORIZON["daily"])


def format_horizon(n: int, frequency: Optional[str]) -> str:
    """'60 días hábiles', '12 meses', '1 trimestre'. None -> 'N pasos' (unit
    not recorded, e.g. snapshots saved before 4.14)."""
    if frequency not in _UNITS:
        return f"{n} paso" if n == 1 else f"{n} pasos"
    singular, plural = _UNITS[frequency]
    return f"{n} {singular if n == 1 else plural}"
