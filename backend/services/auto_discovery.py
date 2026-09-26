"""
AutoDiscoveryEngine — Variant B of EngineSelector, per the design already
documented in docs/ARCHITECTURE.md: instead of only consulting the curated
catalogs from the initial benchmark round (SEASONAL_FRED_CATALOG,
DIVERSIFIED_ETF_CATALOG — useful for the series tested by hand in that round,
but never updated for anything new), any series with enough history that
isn't already in those catalogs gets its OWN mini walk-forward backtest,
comparing Holt vs TimesFM on its real, specific data — not a category's
aggregate evidence from months ago.

This directly answers the scaling problem the curated catalogs have: a series
Gemini brings back today (e.g. IPG3344S, CAPUTL3344S) was never in the
original benchmark round and would otherwise silently fall through to the
Holt default without ever being measured, even if TimesFM would clearly win on
that specific series.

Cost: the mini-backtest runs BOTH engines across a few cutoffs — several
TimesFM inferences instead of one — so the first time a new series is seen,
the forecast request is measurably slower (see AutoDiscoveryEngine.decide()'s
own docstring for measured numbers). Once cached, subsequent requests for the
same series pay zero extra cost until the decision goes stale.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import numpy as np
from sqlalchemy.orm import Session

from backend.database.models import EngineDecisionModel
from backend.services.backtest_engine import BacktestEngine
from backend.services.forecast_engine import DampedHoltForecastEngine, TimesFMForecastEngine
from backend.config import settings

logger = logging.getLogger(__name__)

# Re-evaluate a cached decision after this many days — a market regime shift
# (or TimesFM's own foundation-model weights being upgraded) shouldn't be
# locked in forever from one evaluation. 30 days mirrors the "the market
# changes regime" reasoning already used elsewhere in this project (e.g.
# CACHE_TTL_SECONDS's much shorter TTL for raw data, this is the analogous
# knob for a derived decision that's expensive to recompute).
DECISION_TTL_DAYS = 30

# Re-evaluate even within the TTL window if the series has grown by more than
# this fraction of new points since the last evaluation — e.g. a daily equity
# series accumulates ~21 new trading days/month; if it's grown 20%+ since the
# last check, there's enough new signal that the old decision might no longer
# hold, independent of how many days have passed.
STALE_GROWTH_FRACTION = 0.20

# Minimum history for the mini-backtest to produce a meaningful decision — same
# threshold EngineSelector already uses to flag low-confidence Holt fits (see
# LOW_CONFIDENCE_HISTORY_THRESHOLD in engine_selector.py). Below this, the
# existing cold-start path already handles it; auto-discovery isn't attempted.
MIN_HISTORY_FOR_AUTODISCOVERY = 90

# Mini-backtest parameters: short horizon, few cutoffs — enough for a
# reasonable per-series signal without being as expensive as the original
# 5-cutoff full benchmark (scripts/benchmark_real_data.py).
MINI_BACKTEST_HORIZON = 30
MINI_BACKTEST_N_CUTOFFS = 3

# TimesFM must not just win on MASE — it must do so without a catastrophically
# under-calibrated interval. Same "subcoverage" spirit as
# BacktestEngine.run_backtest's own warning (nominal - 15pp), but wider here
# (30pp) because this is a coarser, cheaper mini-backtest making an automatic
# decision with no human reviewing each one — a stricter bar for catching a
# genuinely bad calibration, not a hair-trigger that flips back to Holt over
# ordinary noise.
MAX_ACCEPTABLE_COVERAGE_GAP_PP = 30.0


def _available_timesfm_engine() -> Optional[TimesFMForecastEngine]:
    """The loaded TimesFM singleton, or None if it can't run in this process.
    See TimesFMForecastEngine.is_available for why this is cheap per request."""
    return TimesFMForecastEngine() if TimesFMForecastEngine.is_available() else None


class AutoDiscoveryEngine:
    """Per-series Holt-vs-TimesFM mini-backtest, cached in SQLite."""

    @staticmethod
    def get_cached_decision(db: Session, series_id: str) -> Optional[EngineDecisionModel]:
        return db.query(EngineDecisionModel).filter(EngineDecisionModel.series_id == series_id).first()

    @staticmethod
    def _is_stale(decision: EngineDecisionModel, current_n_points: int) -> bool:
        age = datetime.now(timezone.utc) - decision.evaluated_at.replace(tzinfo=timezone.utc)
        if age > timedelta(days=DECISION_TTL_DAYS):
            return True
        if decision.n_points_at_evaluation > 0:
            growth = (current_n_points - decision.n_points_at_evaluation) / decision.n_points_at_evaluation
            if growth >= STALE_GROWTH_FRACTION:
                return True
        # mase_timesfm IS NULL with no failed cutoffs means TimesFM was
        # unavailable when this was evaluated: Holt was never compared against
        # anything. Stale as soon as TimesFM can run; while it still can't, a
        # re-run would be Holt-only again, so the regular TTL applies.
        # NULL *with* failed cutoffs means TimesFM was loaded but fell back to
        # Holt on every cutoff of this series: re-running right away would
        # most likely fail the same way, so that also waits for the TTL.
        # Checked last: it's the only condition that may load TimesFM.
        if decision.mase_timesfm is not None or (decision.timesfm_failed_cutoffs or 0) > 0:
            return False
        return _available_timesfm_engine() is not None

    @staticmethod
    def decide(
        db: Session,
        series_id: str,
        n_points: int,
        is_macro: bool = False,
    ) -> Optional[EngineDecisionModel]:
        """
        Returns a cached (possibly freshly-computed) EngineDecisionModel for
        this series, or None if auto-discovery doesn't apply (history too
        short — the caller should fall back to EngineSelector's existing
        cold-start path in that case).

        Measured cost (this repo's dev machine, CPU, 3 cutoffs x 2 engines):
        a NEW series' first call pays ~3 x (Holt ~0.1s + TimesFM ~0.35s) =
        ~1.35s extra before returning the decision. Every later call for the
        same series (until the decision goes stale) is a single indexed SQLite
        lookup — no measurable added latency.
        """
        clean_id = series_id.strip().upper()
        if n_points < MIN_HISTORY_FOR_AUTODISCOVERY:
            return None

        cached = AutoDiscoveryEngine.get_cached_decision(db, clean_id)
        if cached is not None and not AutoDiscoveryEngine._is_stale(cached, n_points):
            return cached

        try:
            decision = AutoDiscoveryEngine._run_mini_backtest(clean_id, is_macro=is_macro, n_points=n_points)
        except Exception as e:
            # A failed mini-backtest (e.g. data provider hiccup) must not break
            # the actual forecast request it was triggered by — fall through to
            # the caller's existing default path instead of raising.
            logger.warning(f"Auto-discovery mini-backtest failed for {clean_id}: {e}", exc_info=True)
            return cached  # stale cached decision is still better than nothing, if one exists

        if cached is not None:
            cached.engine_choice = decision.engine_choice
            cached.evaluated_at = decision.evaluated_at
            cached.mase_holt = decision.mase_holt
            cached.mase_timesfm = decision.mase_timesfm
            cached.n_points_at_evaluation = decision.n_points_at_evaluation
            cached.timesfm_failed_cutoffs = decision.timesfm_failed_cutoffs
            db.commit()
            db.refresh(cached)
            return cached
        else:
            db.add(decision)
            db.commit()
            db.refresh(decision)
            return decision

    @staticmethod
    def _run_mini_backtest(series_id: str, is_macro: bool, n_points: int) -> EngineDecisionModel:
        """
        Runs BacktestEngine.run_backtest (reused, not reimplemented) with an
        explicit engine_override for both Holt and TimesFM across
        MINI_BACKTEST_N_CUTOFFS cutoffs, and picks the winner by mean MASE —
        subject to the coverage-calibration guard below.
        """
        holt_engine = DampedHoltForecastEngine()

        # Availability is checked ONCE up front: if the real model never
        # loaded, there's no point running the mini-backtest against it at all
        # (every cutoff would just be Holt vs Holt). A loaded model can still
        # fail on a given cutoff and answer with Holt internally; that shows up
        # per cutoff as BacktestResponse.is_fallback, handled in the loop.
        timesfm_engine = _available_timesfm_engine()

        cutoffs = AutoDiscoveryEngine._pick_cutoffs(series_id, is_macro)
        if not cutoffs:
            # Raised instead of caching mean([]) = NaN as a "holt" decision: that
            # row would also have mase_timesfm=None, which _is_stale reads as
            # "TimesFM unavailable" and would re-run on every request.
            raise ValueError(f"No hay historia suficiente para ningún cutoff del mini-backtest de {series_id}")

        holt_mases, holt_coverages = [], []
        # Paired results, only for cutoffs where TimesFM really ran: comparing
        # TimesFM's mean over some cutoffs against Holt's over all of them
        # would not be the same test.
        paired_holt_mases, paired_holt_coverages = [], []
        tfm_mases, tfm_coverages = [], []
        tfm_failed_cutoffs = 0

        for cutoff_date in cutoffs:
            holt_res = BacktestEngine.run_backtest(
                series_id=series_id, cutoff_date=cutoff_date, horizon=MINI_BACKTEST_HORIZON,
                is_macro=is_macro, engine_override=holt_engine,
            )
            holt_mases.append(holt_res.metrics.mase)
            holt_coverages.append(holt_res.interval_coverage)

            if timesfm_engine is not None:
                tfm_res = BacktestEngine.run_backtest(
                    series_id=series_id, cutoff_date=cutoff_date, horizon=MINI_BACKTEST_HORIZON,
                    is_macro=is_macro, engine_override=timesfm_engine,
                )
                if tfm_res.is_fallback:
                    # TimesFM failed here and Holt answered in its place: this
                    # MASE is Holt's. Recording it as TimesFM's would be a
                    # fabricated metric, so the cutoff is dropped for both.
                    tfm_failed_cutoffs += 1
                    logger.warning(
                        f"Auto-discovery {series_id} @ {cutoff_date}: TimesFM cayó a Holt "
                        f"({tfm_res.model_name}); cutoff descartado de la comparación."
                    )
                    continue
                tfm_mases.append(tfm_res.metrics.mase)
                tfm_coverages.append(tfm_res.interval_coverage)
                paired_holt_mases.append(holt_res.metrics.mase)
                paired_holt_coverages.append(holt_res.interval_coverage)

        engine_choice = "holt"
        mean_mase_tfm = None

        if tfm_mases:
            mean_mase_holt = float(np.mean(paired_holt_mases))
            mean_coverage_holt = float(np.mean(paired_holt_coverages))
            mean_mase_tfm = float(np.mean(tfm_mases))
            mean_coverage_tfm = float(np.mean(tfm_coverages))
            coverage_gap = mean_coverage_holt - mean_coverage_tfm
            timesfm_wins_mase = mean_mase_tfm < mean_mase_holt
            timesfm_calibration_acceptable = coverage_gap <= MAX_ACCEPTABLE_COVERAGE_GAP_PP
            if timesfm_wins_mase and timesfm_calibration_acceptable:
                engine_choice = "timesfm"
        else:
            # TimesFM unavailable, or it fell back on every cutoff: Holt alone.
            mean_mase_holt = float(np.mean(holt_mases))

        return EngineDecisionModel(
            series_id=series_id,
            engine_choice=engine_choice,
            evaluated_at=datetime.now(timezone.utc),
            mase_holt=mean_mase_holt,
            mase_timesfm=mean_mase_tfm,
            n_points_at_evaluation=n_points,
            timesfm_failed_cutoffs=tfm_failed_cutoffs if timesfm_engine is not None else None,
        )

    @staticmethod
    def _pick_cutoffs(series_id: str, is_macro: bool) -> list:
        """Picks MINI_BACKTEST_N_CUTOFFS cutoff dates spaced over the recent
        history of the series, each leaving MINI_BACKTEST_HORIZON points for
        evaluation — mirrors scripts/benchmark_real_data.py's walk-forward
        spacing logic, at a smaller scale for the per-request cost this incurs."""
        if is_macro:
            from backend.services.data_fetcher import FREDDataFetcher
            data = FREDDataFetcher().get_series(series_id)
        else:
            from backend.services.data_fetcher import MarketDataFetcher
            data = MarketDataFetcher.get_history(series_id, period="5y")

        sorted_points = sorted(data.points, key=lambda p: p.timestamp)
        n = len(sorted_points)
        min_train = max(30, MINI_BACKTEST_HORIZON * 2)
        last_possible = n - MINI_BACKTEST_HORIZON

        if last_possible <= min_train:
            return [sorted_points[min_train - 1].timestamp] if min_train <= n else []

        step = (last_possible - min_train) / max(1, MINI_BACKTEST_N_CUTOFFS - 1)
        indices = sorted(set(
            int(round(min_train + i * step)) for i in range(MINI_BACKTEST_N_CUTOFFS)
        ))
        return [sorted_points[idx - 1].timestamp for idx in indices if 0 < idx <= n]
