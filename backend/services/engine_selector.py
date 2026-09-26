"""
EngineSelector — per-series forecast engine selection, evidence-based.
========================================================================
Replaces the single global USE_REAL_TIMESFM on/off switch with a per-series
decision, backed by `scripts/benchmark_real_data.py`'s real walk-forward
benchmark (FRED + yfinance data, TimesFM vs Damped Holt vs Naive RW).

RULE: a category only routes to TimesFM if the benchmark showed TimesFM winning
(lower mean MASE) in >=50% of that category's representative series. This is
NOT a heuristic guess at what "should" work well — every category below is
backed by that measurement, and categories where the hypothesis did NOT hold
are called out explicitly rather than silently omitted.

Benchmark results (5 walk-forward cutoffs per series, real data, run 2026-09-22):

  Seasonal FRED series (IPG2211A2N, RSAFSNA, HOUSTNSA, MRTSSM4451USN):
    The 2026-09-22 round (TimesFM vs Holt only) had TimesFM 4/4. Re-measured on
    2026-09-26 against a fair seasonal rival (Holt-Winters, seasonal naive,
    Prophet; docs/results/seasonal_benchmark_2026-09-26.md): TimesFM beats
    Holt-Winters firmly on IPG2211A2N, probably on HOUSTNSA and RSAFSNA (the
    latter fragile without 2020), and not significantly on MRTSSM4451USN.
    -> Per-series entries in SEASONAL_FRED_CATALOG, each with its evidence.

  Diversified index/sector ETFs (SPY, QQQ, XLE, XLK):
    TimesFM won 0/4 (0%) — Holt/Naive RW matched or beat TimesFM on all four.
    The initial hypothesis ("diversified baskets favor TimesFM") did NOT hold.
    -> Stays on Holt. No ETF/index special-casing toward TimesFM.

  Cold-start (AAPL/MSFT/NVDA/JNJ, context truncated to 30/60/90 days):
    TimesFM won at most 1/4 (25%) at any window size (30d, 60d, or 90d) — never
    reaching the 50% bar. The initial hypothesis ("short history favors TimesFM,
    a foundation model needs less context to generalize") did NOT hold either.
    -> Stays on Holt. Short history instead gets a low-confidence warning in
    fitted_params, because the actual risk with few points is an unreliable
    MLE fit (few residuals to estimate sigma from) — not the wrong engine.

  Individual equities, full history (AAPL/MSFT/NVDA/JNJ, baseline):
    TimesFM won 2/4 (50%) — exactly at the threshold, but this is the existing
    default behavior (Holt), not a new category being added to a catalog, so it
    is left unchanged per the task's own instruction.

BEYOND THE CATALOGS: these curated catalogs only cover series tested by hand in
the original benchmark round — any new series (e.g. one Gemini brings back that
was never part of that round) used to silently fall through to the Holt default
without ever being measured. `backend/services/auto_discovery.py`'s
AutoDiscoveryEngine (Variant B, see docs/ARCHITECTURE.md) now runs a per-series
mini-backtest for anything outside both catalogs with enough history, and
caches the result in SQLite — see `select()`'s `db` parameter below.
"""

import logging
from typing import List, Optional
from sqlalchemy.orm import Session

from backend.config import settings
from backend.schemas.models import TimeSeriesPoint, ForecastResponse
from dataclasses import dataclass

from backend.services.forecast_engine import (
    BaseForecastEngine,
    DampedHoltForecastEngine,
    HoltWintersForecastEngine,
    TimesFMForecastEngine,
)
from backend.services.seasonality import detect_seasonality

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SeasonalCatalogEntry:
    """One curated seasonal series: which engine, how solid the evidence is,
    and where the result lives. `evidence` is what the user reads."""
    engine: str      # "timesfm" | "holt_winters"
    strength: str    # "firme" | "probable" | "probable, frágil" | "no significativa"
    evidence: str
    result_ref: str


_SEASONAL_RESULT = "docs/results/seasonal_benchmark_2026-09-26.md"

# Curated catalogs — explicit membership, never inferred from name/ticker shape.
# Seasonal entries come from the 3.0c+d benchmark (paired sign test against
# Holt-Winters, 24 cutoffs; "firme" = survives Bonferroni over the 4 series,
# alpha 0.0125).
SEASONAL_FRED_CATALOG = {
    "IPG2211A2N": SeasonalCatalogEntry(
        "timesfm", "firme",
        "le ganó a Holt-Winters en 20 de 24 cutoffs (p=0,002; sobrevive a Bonferroni)",
        _SEASONAL_RESULT),
    "HOUSTNSA": SeasonalCatalogEntry(
        "timesfm", "probable",
        "le ganó a Holt-Winters en 18 de 24 cutoffs (p=0,023; no sobrevive a Bonferroni)",
        _SEASONAL_RESULT),
    "RSAFSNA": SeasonalCatalogEntry(
        "timesfm", "probable, frágil",
        "le ganó a Holt-Winters en 18 de 24 cutoffs (p=0,023); sin las ventanas de 2020, "
        "16 de 22 (p=0,052) y ganaría Holt-Winters",
        _SEASONAL_RESULT),
    "MRTSSM4451USN": SeasonalCatalogEntry(
        "holt_winters", "no significativa",
        "TimesFM tuvo menor error medio pero no le ganó a Holt-Winters de forma "
        "significativa (16 de 24 cutoffs, p=0,152)",
        _SEASONAL_RESULT),
}
DIVERSIFIED_ETF_CATALOG = {"SPY", "QQQ", "XLE", "XLK"}

# Below this many points, Holt's MLE fit has too few residuals for sigma to be
# a trustworthy variance estimate (not a TimesFM-vs-Holt accuracy question — the
# benchmark found no history-length threshold where TimesFM actually wins; see
# docstring). This is only used to flag low confidence in fitted_params.
LOW_CONFIDENCE_HISTORY_THRESHOLD = 90

# Same threshold as auto_discovery.MIN_HISTORY_FOR_AUTODISCOVERY (imported
# directly, not duplicated as a literal) — a series needs at least this many
# points before a per-series mini-backtest produces a meaningful decision.
AUTO_DISCOVERY_MIN_HISTORY = LOW_CONFIDENCE_HISTORY_THRESHOLD


class EngineSelector:
    """Chooses a forecast engine for one specific series and reports why."""

    @staticmethod
    def select(
        points: List[TimeSeriesPoint],
        series_id: Optional[str] = None,
        series_type: Optional[str] = None,
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D",
        db: Optional[Session] = None,
    ) -> ForecastResponse:
        """Runs the appropriate engine for this series and returns its
        ForecastResponse with `engine_selection_reason` filled in.

        Callers pass the same `points` they'd pass to any BaseForecastEngine —
        this does not fetch data itself, it only decides which engine runs.

        `db`: optional SQLAlchemy session. When provided AND the series isn't
        in either curated catalog AND has enough history, this enables
        Variant B auto-discovery (backend/services/auto_discovery.py) — a
        per-series mini-backtest whose result is cached in SQLite instead of
        silently falling through to the Holt default for any series that was
        never part of the original benchmark round. Callers that don't pass
        `db` (or pass None) simply skip auto-discovery and keep the old
        catalog-only behavior — this keeps `db` optional rather than required,
        since not every caller of EngineSelector has a session handy.
        """
        clean_id = (series_id or "").strip().upper()
        n_points = len(points)

        if clean_id and clean_id in SEASONAL_FRED_CATALOG:
            entry = SEASONAL_FRED_CATALOG[clean_id]
            if entry.engine == "timesfm":
                return EngineSelector._run_with_timesfm_preference(
                    points,
                    horizon=horizon,
                    confidence=confidence,
                    freq=freq,
                    reason_if_real=(
                        f"Serie FRED estacional ({clean_id}) — TimesFM por catálogo, evidencia "
                        f"{entry.strength}: {entry.evidence} (ver {entry.result_ref})."
                    ),
                )
            return EngineSelector._run_holt_winters_or_holt(
                points, horizon=horizon, confidence=confidence, freq=freq,
                reason_if_ok=(
                    f"Serie FRED estacional ({clean_id}) — Holt-Winters por catálogo: "
                    f"{entry.evidence} (ver {entry.result_ref})."
                ),
            )

        if clean_id and clean_id in DIVERSIFIED_ETF_CATALOG:
            return EngineSelector._run_holt(
                points,
                horizon=horizon,
                confidence=confidence,
                freq=freq,
                reason=(
                    f"Índice/ETF diversificado ({clean_id}) — Holt (default): "
                    f"TimesFM no le ganó a Holt en esta categoría en el benchmark "
                    f"real (0/4 series), pese a la hipótesis inicial de que series "
                    f"diversificadas favorecerían a TimesFM."
                ),
            )

        if db is not None and clean_id and n_points >= AUTO_DISCOVERY_MIN_HISTORY:
            auto_result = EngineSelector._try_auto_discovery(
                db, clean_id, series_type, points, n_points, horizon, confidence, freq,
            )
            if auto_result is not None:
                return auto_result

        if n_points < LOW_CONFIDENCE_HISTORY_THRESHOLD:
            return EngineSelector._run_holt(
                points,
                horizon=horizon,
                confidence=confidence,
                freq=freq,
                reason=(
                    f"Historia insuficiente ({n_points} puntos < umbral de "
                    f"{LOW_CONFIDENCE_HISTORY_THRESHOLD}) — Holt con advertencia de "
                    f"baja confianza: el benchmark real no encontró ninguna ventana "
                    f"de historia corta (30/60/90d) donde TimesFM superara a Holt en "
                    f"≥50% de los casos, así que no se cambia de motor; el riesgo "
                    f"real es un ajuste MLE poco confiable con tan pocos residuos."
                ),
                low_confidence=True,
            )

        return EngineSelector._run_holt(
            points,
            horizon=horizon,
            confidence=confidence,
            freq=freq,
            reason="Acción individual, historia suficiente — Holt (default).",
        )

    @staticmethod
    def _try_auto_discovery(
        db: Session,
        clean_id: str,
        series_type: Optional[str],
        points: List[TimeSeriesPoint],
        n_points: int,
        horizon: int,
        confidence: float,
        freq: str,
    ) -> Optional[ForecastResponse]:
        """Consults (or triggers) Variant B auto-discovery for a series outside
        both curated catalogs. Returns None if auto-discovery couldn't produce
        a decision (e.g. the mini-backtest itself failed) — the caller then
        falls through to the existing cold-start/default path unchanged."""
        from backend.services.auto_discovery import AutoDiscoveryEngine

        is_macro = series_type == "macro"
        decision = AutoDiscoveryEngine.decide(db, clean_id, n_points, is_macro=is_macro)
        if decision is None:
            return None

        # What TimesFM was compared against: Holt, or Holt-Winters with the
        # seasonal MASE for seasonal series (criterion v3). NULL = legacy Holt.
        base = decision.baseline_engine or "holt"
        base_label = "Holt-Winters" if base == "holt_winters" else "Holt"
        metric = "MASE estacional" if decision.metric == "mase_seasonal" else "MASE"
        date = decision.evaluated_at.strftime('%Y-%m-%d')
        mase_base = decision.mase_holt  # error of the baseline engine (see baseline_engine)

        # Cutoffs where TimesFM fell back to Holt were dropped from the
        # comparison (see AutoDiscoveryEngine._run_mini_backtest); say so.
        failed = decision.timesfm_failed_cutoffs or 0
        dropped_note = (
            f" TimesFM falló en {failed} cutoff(s) del mini-backtest (cayó a Holt internamente); "
            f"la comparación usa solo aquellos donde corrió de verdad."
            if failed and decision.mase_timesfm is not None else ""
        )

        if decision.engine_choice == "timesfm":
            won = (f"TimesFM ganó {metric} {decision.mase_timesfm:.3f} vs {base_label} "
                   f"{mase_base:.3f} en un mini-backtest de esta serie puntual")
            attempt = None
            if settings.USE_REAL_TIMESFM:
                attempt = TimesFMForecastEngine().forecast(points, horizon=horizon, confidence=confidence, freq=freq)
                if not attempt.is_fallback:
                    attempt.engine_selection_reason = f"Auto-evaluado el {date}: {won}." + dropped_note
                    return attempt
                problem = f"TimesFM no corrió ahora ({attempt.fallback_reason or 'sin motivo informado'})"
            else:
                problem = "USE_REAL_TIMESFM=false en este entorno"
            res = EngineSelector._plan_b(points, horizon, confidence, freq, attempt)
            res.engine_selection_reason = f"Auto-evaluado el {date}: {won}, pero {problem}. " + res.engine_selection_reason
            return EngineSelector._append(res, dropped_note)

        if base == "holt_winters":
            res = EngineSelector._run_holt_winters_or_holt(
                points, horizon=horizon, confidence=confidence, freq=freq, reason_if_ok="",
            )
            prefix = res.engine_selection_reason  # non-empty only if HW failed and Holt answered
        else:
            res = DampedHoltForecastEngine().forecast(points, horizon=horizon, confidence=confidence, freq=freq)
            prefix = ""

        if decision.mase_timesfm is not None and decision.mase_timesfm < mase_base:
            # TimesFM had the better (lower) error but was disqualified by the
            # calibration guard — "X ganó" would be false; say what happened.
            reason = (
                f"Auto-evaluado el {date}: TimesFM tuvo mejor {metric} ({decision.mase_timesfm:.3f} vs "
                f"{base_label} {mase_base:.3f}) pero su intervalo de confianza quedó mal calibrado en el "
                f"mini-backtest — {base_label} (elegido por calibración, no porque haya ganado en {metric})."
            )
        elif decision.mase_timesfm is None and failed:
            # TimesFM was loaded but fell back to Holt on every cutoff: no real
            # TimesFM error to compare. Not re-evaluated early; regular TTL.
            reason = (
                f"Auto-evaluado el {date}: TimesFM falló en los {failed} cutoff(s) del mini-backtest de esta "
                f"serie (cayó a Holt internamente), así que no hay {metric} real de TimesFM — {base_label} "
                f"({metric} {mase_base:.3f}) sin comparación; se re-evalúa con el TTL normal."
            )
        elif decision.mase_timesfm is None:
            # TimesFM couldn't run at evaluation time: nothing was compared, so
            # "ganó" would be false. _is_stale re-evaluates as soon as it can.
            reason = (
                f"Auto-evaluado el {date} con TimesFM no disponible: TimesFM no evaluado, {base_label} "
                f"({metric} {mase_base:.3f}) sin comparación — se re-evalúa apenas TimesFM esté disponible, "
                f"sin esperar el TTL."
            )
        else:
            reason = (
                f"Auto-evaluado el {date}: {base_label} ganó {metric} {mase_base:.3f} vs TimesFM "
                f"{decision.mase_timesfm:.3f} en un mini-backtest de esta serie puntual — {base_label} "
                f"(elegido por auto-evaluación, no por catálogo ni default)."
            )
        res.engine_selection_reason = f"{prefix} {reason}" if prefix else reason
        return EngineSelector._append(res, dropped_note)

    @staticmethod
    def _append(res: ForecastResponse, note: str) -> ForecastResponse:
        res.engine_selection_reason += note
        return res

    @staticmethod
    def _run_holt(
        points: List[TimeSeriesPoint],
        reason: str,
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D",
        low_confidence: bool = False,
    ) -> ForecastResponse:
        engine = DampedHoltForecastEngine()
        res = engine.forecast(points, horizon=horizon, confidence=confidence, freq=freq)
        res.engine_selection_reason = reason
        if low_confidence and res.fitted_params is not None:
            res.fitted_params["low_confidence"] = 1.0
        return res

    @staticmethod
    def _run_holt_winters_or_holt(
        points: List[TimeSeriesPoint],
        reason_if_ok: str,
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D",
    ) -> ForecastResponse:
        """Holt-Winters; if it fails (not seasonal in this window, too little
        history, fit error) Holt answers, with the reason — never silently.
        On success the reason is `reason_if_ok`; on failure it says why."""
        try:
            res = HoltWintersForecastEngine().forecast(points, horizon=horizon, confidence=confidence, freq=freq)
            res.engine_selection_reason = reason_if_ok
            return res
        except Exception as e:
            logger.warning(f"Holt-Winters falló ({type(e).__name__}: {e}); se usa Holt.")
            res = DampedHoltForecastEngine().forecast(points, horizon=horizon, confidence=confidence, freq=freq)
            res.is_fallback = True
            res.engine_selection_reason = (
                f"Holt-Winters no pudo correr ({e}) — usando Holt como fallback transparente."
            )
            return res

    @staticmethod
    def _plan_b(
        points: List[TimeSeriesPoint],
        horizon: int,
        confidence: float,
        freq: str,
        timesfm_attempt: Optional[ForecastResponse],
    ) -> ForecastResponse:
        """What runs when TimesFM was preferred but can't run (unavailable or
        failed): Holt-Winters for series the 3.0a detector marks seasonal
        (Holt loses even to the seasonal naive there, 3.0d), Holt otherwise.
        TimesFM's fallback cause (if it was attempted) is kept on the response;
        model_name is always the engine that actually ran."""
        seasonality = detect_seasonality(points)
        if seasonality.is_seasonal:
            res = EngineSelector._run_holt_winters_or_holt(
                points, horizon=horizon, confidence=confidence, freq=freq,
                reason_if_ok=(
                    f"Plan B estacional: Holt-Winters ({seasonality.reason}) En series estacionales, "
                    f"Holt pierde incluso contra el naive estacional (benchmark 3.0d)."
                ),
            )
        else:
            res = EngineSelector._run_holt(
                points, horizon=horizon, confidence=confidence, freq=freq,
                reason=f"Plan B: Holt, serie no estacional ({seasonality.reason})",
            )
        res.is_fallback = True
        if timesfm_attempt is not None:
            res.fallback_kind = timesfm_attempt.fallback_kind
            res.fallback_reason = timesfm_attempt.fallback_reason
        return res

    @staticmethod
    def _run_with_timesfm_preference(
        points: List[TimeSeriesPoint],
        reason_if_real: str,
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D",
    ) -> ForecastResponse:
        """Tries TimesFM; if it's unavailable or fails, runs the plan B
        (Holt-Winters for seasonal series, Holt otherwise) with an explicit
        reason — never silently serves another engine while claiming TimesFM."""
        attempt = None
        if settings.USE_REAL_TIMESFM:
            attempt = TimesFMForecastEngine().forecast(points, horizon=horizon, confidence=confidence, freq=freq)
            if not attempt.is_fallback:
                attempt.engine_selection_reason = reason_if_real
                return attempt
            problem = f"TimesFM no corrió ({attempt.fallback_reason or 'sin motivo informado'})"
        else:
            problem = "USE_REAL_TIMESFM=false en este entorno"
        res = EngineSelector._plan_b(points, horizon, confidence, freq, attempt)
        res.engine_selection_reason = (
            f"El catálogo indica TimesFM, pero {problem}. " + res.engine_selection_reason
        )
        return res
