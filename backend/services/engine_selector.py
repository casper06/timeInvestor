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
    TimesFM won 4/4 (100%) — MASE 0.41-1.42 (TimesFM) vs 0.87-4.12 (Holt).
    -> Routes to TimesFM.

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
from backend.services.forecast_engine import (
    BaseForecastEngine,
    DampedHoltForecastEngine,
    TimesFMForecastEngine,
)

logger = logging.getLogger(__name__)

# Curated catalogs — explicit membership, never inferred from name/ticker shape.
# Each entry here is backed by the benchmark documented in this module's docstring.
SEASONAL_FRED_CATALOG = {"IPG2211A2N", "RSAFSNA", "HOUSTNSA", "MRTSSM4451USN"}
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
            return EngineSelector._run_with_timesfm_preference(
                points,
                horizon=horizon,
                confidence=confidence,
                freq=freq,
                reason_if_real=(
                    f"Serie FRED estacional ({clean_id}) — TimesFM seleccionado: "
                    f"ganó 4/4 series de esta categoría en el benchmark real "
                    f"(MASE muy inferior a Holt)."
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

        if decision.engine_choice == "timesfm" and settings.USE_REAL_TIMESFM:
            engine = TimesFMForecastEngine()
            res = engine.forecast(points, horizon=horizon, confidence=confidence, freq=freq)
            if not res.is_fallback:
                res.engine_selection_reason = (
                    f"Auto-evaluado el {decision.evaluated_at.strftime('%Y-%m-%d')}: "
                    f"TimesFM ganó MASE {decision.mase_timesfm:.3f} vs Holt "
                    f"{decision.mase_holt:.3f} en un mini-backtest de esta serie puntual."
                )
                return res
            res.engine_selection_reason = (
                f"Auto-evaluado el {decision.evaluated_at.strftime('%Y-%m-%d')} — TimesFM había "
                f"ganado MASE {decision.mase_timesfm:.3f} vs Holt {decision.mase_holt:.3f}, pero "
                f"TimesFM no está disponible ahora mismo — usando Holt como fallback transparente."
            )
            return res

        engine = DampedHoltForecastEngine()
        res = engine.forecast(points, horizon=horizon, confidence=confidence, freq=freq)
        if decision.engine_choice == "timesfm":
            res.engine_selection_reason = (
                f"Auto-evaluado el {decision.evaluated_at.strftime('%Y-%m-%d')} — TimesFM había "
                f"ganado MASE {decision.mase_timesfm:.3f} vs Holt {decision.mase_holt:.3f}, pero "
                f"USE_REAL_TIMESFM=false en este entorno — usando Holt como fallback transparente."
            )
        else:
            mase_tfm_str = f"{decision.mase_timesfm:.3f}" if decision.mase_timesfm is not None else "no evaluado"
            res.engine_selection_reason = (
                f"Auto-evaluado el {decision.evaluated_at.strftime('%Y-%m-%d')}: Holt ganó MASE "
                f"{decision.mase_holt:.3f} vs TimesFM {mase_tfm_str} en un mini-backtest de esta "
                f"serie puntual — Holt (elegido por auto-evaluación, no por catálogo ni default)."
            )
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
    def _run_with_timesfm_preference(
        points: List[TimeSeriesPoint],
        reason_if_real: str,
        horizon: int = 30,
        confidence: float = 0.95,
        freq: str = "D",
    ) -> ForecastResponse:
        """Tries TimesFM; falls back to Holt with an explicit reason if it's
        unavailable (USE_REAL_TIMESFM=false or weights failed to load) — never
        silently serves Holt while claiming TimesFM was used."""
        if settings.USE_REAL_TIMESFM:
            engine = TimesFMForecastEngine()
            res = engine.forecast(points, horizon=horizon, confidence=confidence, freq=freq)
            if not res.is_fallback:
                res.engine_selection_reason = reason_if_real
                return res
            # TimesFMForecastEngine already fell back to Holt internally (weights
            # failed to load despite USE_REAL_TIMESFM=true) — report that plainly.
            res.engine_selection_reason = (
                "Categoría favorece TimesFM por benchmark, pero TimesFM no está "
                "disponible (pesos no cargados) — usando Holt como fallback transparente."
            )
            return res

        engine = DampedHoltForecastEngine()
        res = engine.forecast(points, horizon=horizon, confidence=confidence, freq=freq)
        res.engine_selection_reason = (
            "Categoría favorece TimesFM por benchmark, pero USE_REAL_TIMESFM=false "
            "en este entorno — usando Holt como fallback transparente."
        )
        return res
