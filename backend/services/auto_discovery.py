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
from backend.services.forecast_engine import DampedHoltForecastEngine, NotSeasonalError, TimesFMForecastEngine
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
# Up to criterion v4 every frequency was evaluated at 30 steps. Kept for the
# scripts that reproduce 2.2/2.3 and as the meaning of a NULL
# engine_decisions.horizon; from v5 the horizon is _decision_horizon().
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

# Coverage is compared at the SAME nominal level for both engines. TimesFM only
# has a p10-p90 band (80%), so Holt is evaluated at 80% too (its analytic
# interval allows any level); TimesFM is never stretched to 95%.
GUARD_INTERVAL_LEVEL = 0.80

# Version of the evaluation criterion stored with each decision. A decision
# made with an older version is stale (re-evaluated on the next request),
# instead of deleting rows by hand. NULL = rows from before this column (v1).
#   v1: TimesFM band read as [mean, p90] (column 0 taken as p10), and Holt's
#       95% coverage compared against TimesFM's "80%" band.
#   v2 (2026-09-26, 3.0e): TimesFM band = real p10-p90 (by quantile value);
#       both engines compared at GUARD_INTERVAL_LEVEL (80%).
#   v3 (2026-09-26, 3.0f): for series the 3.0a detector marks seasonal, the
#       baseline is Holt-Winters (not Holt) and the metric is the seasonally
#       scaled MASE; non-seasonal series keep Holt and the 1-step MASE.
#   v4 (2026-09-26, 2.3): robust rule (decide_robust): 8 cutoffs over a
#       recent window by frequency, majority of paired cutoffs + 10% margin,
#       >= 7 pairs, tie -> baseline, hysteresis on re-evaluation, no
#       coverage guard. Measured in docs/results/decision_variants_2026-09-26.md.
#   v5 (2026-09-27, 2.3d): same rule, but the mini-backtest evaluates at the
#       canonical horizon of the series' frequency (backend/services/horizons.py:
#       daily 60, weekly 13, monthly 12, quarterly 4) instead of 30 steps for
#       every frequency. Adopted by its pre-registered criterion (db4fcdb) on
#       the 3.5 series (docs/results/fred_category_benchmark_2026-09-27.md);
#       quarterly had no evidence there and was decided by use (docs/adr/0019).
#   v6 (2026-09-27, 2.10): same as v5, but the MASE is never computed with
#       + epsilon. If it's undefined on some cutoff (the series didn't move in
#       that training window), the whole series is decided on the paired MAE
#       (docs/adr/0020). v5 decisions of such series carried MASE values like
#       2.5 million (DFEDTARU); bumping the version re-decides every series.
AUTO_DISCOVERY_CRITERIA_VERSION = 6

# --- v4 decision parameters (2.3), chosen from the variant measurement ---
# 8 cutoffs: the paired pairs cost ~1.0-1.5 s of CPU per series (measured),
# and with fewer cutoffs a decision is close to a coin flip in equities/ETFs.
DECISION_N_CUTOFFS = 8
# Recent evaluation window by frequency (points): daily 2 years, weekly 2
# years, monthly 10 years, quarterly 10 years. Spreading cutoffs over ALL the
# history put FRED cutoffs in 1989 (60 months of training, a remote regime),
# which is what biased IPG2211A2N toward Holt-Winters with 3 cutoffs.
RECENT_WINDOW = {"daily": 504, "weekly": 104, "monthly": 120, "quarterly": 40}
RECENT_WINDOW_DEFAULT = 504
# TimesFM must beat the baseline on a MAJORITY of paired cutoffs AND by at
# least this margin on the mean error. A one-sided sign test (alpha 0.05)
# was measured too: with 8 cutoffs it needs 7/8 and discarded clear wins
# (UNRATE, HOUSTNSA), so a plain majority + margin is used (alpha=None).
DECISION_MARGIN = 0.10
DECISION_ALPHA = None
MIN_PAIRED_CUTOFFS = 7          # of 8: tolerates one TimesFM fallback
# Switching away from the current engine on re-evaluation requires beating it
# with margin * HYSTERESIS_FACTOR (20%).
HYSTERESIS_FACTOR = 2.0
# The coverage guard changed 0-7% of decisions (2.2) and ~0 pp in 2.3 once
# the TimesFM band was fixed (#29): removed from the rule.
USE_COVERAGE_GUARD = False


def choose_engine(baseline_name: str, paired_base: list, paired_base_cov: list,
                  tfm: list, tfm_cov: list) -> str:
    """The mini-backtest's decision rule, on paired per-cutoff results (same
    cutoffs for both engines): TimesFM if its mean metric is strictly lower
    AND its mean coverage is at most MAX_ACCEPTABLE_COVERAGE_GAP_PP below the
    baseline's; the baseline otherwise. Pure, so scripts/decision_stability.py
    can measure exactly this rule."""
    if not tfm:
        return baseline_name
    wins_metric = float(np.mean(tfm)) < float(np.mean(paired_base))
    coverage_gap = float(np.mean(paired_base_cov)) - float(np.mean(tfm_cov))
    if wins_metric and coverage_gap <= MAX_ACCEPTABLE_COVERAGE_GAP_PP:
        return "timesfm"
    return baseline_name


def decide_robust(baseline_name: str, base_errors: list, tfm_errors: list,
                  base_cov: list = None, tfm_cov: list = None, *,
                  margin: float, alpha, min_paired: int, guard: bool,
                  incumbent: str = None, hysteresis_factor: float = 1.0) -> tuple:
    """Robust decision on PAIRED per-cutoff errors (same cutoffs, same order).
    Returns (choice, info).

    X "beats" Y when, on the paired cutoffs, X has the lower error on a
    majority (one-sided sign test at `alpha`; alpha=None means a plain
    majority, wins > losses) AND mean(X) <= (1 - margin) * mean(Y).
    - Fewer than `min_paired` pairs -> baseline (not enough evidence).
    - No incumbent: TimesFM only if it beats the baseline (and, with
      `guard`, its coverage is at most MAX_ACCEPTABLE_COVERAGE_GAP_PP below);
      otherwise the baseline (a tie goes to the baseline).
    - Incumbent (hysteresis): switching away from it requires the other
      engine to beat it with margin * hysteresis_factor; otherwise it stays.
    """
    from scipy import stats as _stats

    n = len(tfm_errors)
    info = {"paired": n}
    if n < min_paired:
        info["why"] = f"solo {n} cutoffs en par (< {min_paired})"
        return baseline_name, info
    # Baseline error exactly 0 on every paired cutoff (a step series whose
    # rounded forecast is exact, e.g. DFEDTARU): nothing to improve on. The
    # baseline wins, and if TimesFM is also 0 it's a tie, which goes to the
    # baseline too, with or without an incumbent (2.8). Before this, the
    # rel_gap ratio below divided by 0 and decide() fell back to no decision.
    if float(np.mean(base_errors)) == 0.0:
        info.update({"why": "error del motor base = 0 en todos los cutoffs",
                     "tie": float(np.mean(tfm_errors)) == 0.0, "rel_gap": None})
        return baseline_name, info

    def beats(a, b, m):
        wins = sum(x < y for x, y in zip(a, b))
        losses = sum(x > y for x, y in zip(a, b))
        if alpha is None:
            consistent = wins > losses
            p = None
        else:
            p = float(_stats.binomtest(wins, wins + losses, 0.5, alternative="greater").pvalue) if wins + losses else 1.0
            consistent = p < alpha
        return consistent and float(np.mean(a)) <= (1.0 - m) * float(np.mean(b)), wins, losses, p

    guard_ok = True
    if guard and base_cov and tfm_cov:
        guard_ok = float(np.mean(base_cov)) - float(np.mean(tfm_cov)) <= MAX_ACCEPTABLE_COVERAGE_GAP_PP

    switch_margin = margin * hysteresis_factor
    if incumbent == "timesfm":
        base_wins, w, l, p = beats(base_errors, tfm_errors, switch_margin)
        choice = baseline_name if (base_wins or not guard_ok) else "timesfm"
    else:
        m = switch_margin if incumbent == baseline_name else margin
        tfm_wins, w, l, p = beats(tfm_errors, base_errors, m)
        choice = "timesfm" if (tfm_wins and guard_ok) else baseline_name
    info.update({"wins": w, "losses": l, "p": p, "guard_ok": guard_ok,
                 "rel_gap": float(np.mean(tfm_errors)) / float(np.mean(base_errors)) - 1.0})
    return choice, info


class InsufficientHistoryError(ValueError):
    """The series is too short for the rule to decide at its horizon: fewer
    points than min_history_for_decision(). Not a failure to hide: the
    selector says it in the reason and serves its default engine."""

    def __init__(self, series_id: str, n: int, required: int, horizon: int):
        self.series_id, self.n, self.required, self.horizon = series_id, n, required, horizon
        super().__init__(f"Historia insuficiente para evaluar {series_id}: {n} de {required} puntos "
                         f"(horizonte {horizon})")


def min_history_for_decision(horizon: int) -> int:
    """Fewest points for which recent_cutoff_indices leaves at least
    MIN_PAIRED_CUTOFFS distinct cutoffs at this horizon: max(30, 2h) of
    training, h to evaluate, and room for the other cutoffs. Below that the
    rule could only answer "baseline, not enough pairs" (daily 60 -> 186,
    weekly 13 -> 49, monthly 12 -> 48, quarterly 4 -> 40)."""
    return max(30, horizon * 2) + horizon + (MIN_PAIRED_CUTOFFS - 1)


def recent_cutoff_indices(n: int, n_cutoffs: int, window: int, horizon: int = None) -> list:
    """0-based indices of `n_cutoffs` cutoffs evenly spaced over the most
    recent `window` points (never before MIN training), each leaving
    `horizon` points after it (default MINI_BACKTEST_HORIZON)."""
    horizon = MINI_BACKTEST_HORIZON if horizon is None else horizon
    min_train = max(30, horizon * 2)
    last = n - 1 - horizon
    first = max(min_train - 1, n - window)
    if last < first:
        return []
    if n_cutoffs == 1 or last == first:
        return [last]
    return sorted({int(round(x)) for x in np.linspace(first, last, n_cutoffs)})


def pick_cutoff_indices(n: int) -> list:
    """0-based indices of the MINI_BACKTEST_N_CUTOFFS cutoffs for a series of
    n points: evenly spaced, each leaving MINI_BACKTEST_HORIZON points after
    it (mirrors scripts/benchmark_real_data.py's walk-forward spacing)."""
    min_train = max(30, MINI_BACKTEST_HORIZON * 2)
    last_possible = n - MINI_BACKTEST_HORIZON
    if last_possible <= min_train:
        return [min_train - 1] if min_train <= n else []
    step = (last_possible - min_train) / max(1, MINI_BACKTEST_N_CUTOFFS - 1)
    indices = sorted(set(int(round(min_train + i * step)) for i in range(MINI_BACKTEST_N_CUTOFFS)))
    return [idx - 1 for idx in indices if 0 < idx <= n]


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
        if (decision.criteria_version or 1) < AUTO_DISCOVERY_CRITERIA_VERSION:
            return True
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

        Measured cost with criterion v4 (DECISION_N_CUTOFFS = 8 cutoffs x 2
        engines, 30 steps): 2.2-3.0 s per new series end to end, data
        download included (docs/results/decision_variants_2026-09-26.md).
        v5 changes only the horizon (daily 60 steps doubles the forecast
        length; monthly 12 shortens it); not re-measured separately. Every later call for
        the same series (until the decision goes stale) is a single indexed
        SQLite lookup — no measurable added latency.
        """
        clean_id = series_id.strip().upper()
        if n_points < MIN_HISTORY_FOR_AUTODISCOVERY:
            return None

        cached = AutoDiscoveryEngine.get_cached_decision(db, clean_id)
        if cached is not None and not AutoDiscoveryEngine._is_stale(cached, n_points):
            return cached

        # Hysteresis: a stale decision made with the CURRENT criterion is the
        # incumbent; switching away from it needs more evidence. A decision
        # from an older criterion is re-decided from scratch.
        incumbent = None
        if cached is not None and (cached.criteria_version or 1) == AUTO_DISCOVERY_CRITERIA_VERSION:
            incumbent = cached.engine_choice
        try:
            decision = AutoDiscoveryEngine._run_mini_backtest(
                clean_id, is_macro=is_macro, n_points=n_points, incumbent=incumbent)
        except InsufficientHistoryError:
            raise  # not a hiccup: the selector says it in the reason
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
            cached.criteria_version = decision.criteria_version
            cached.baseline_engine = decision.baseline_engine
            cached.metric = decision.metric
            cached.baseline_skipped_cutoffs = decision.baseline_skipped_cutoffs
            cached.horizon = decision.horizon
            db.commit()
            db.refresh(cached)
            return cached
        else:
            db.add(decision)
            db.commit()
            db.refresh(decision)
            return decision

    @staticmethod
    def _run_mini_backtest(series_id: str, is_macro: bool, n_points: int,
                           incumbent: Optional[str] = None) -> EngineDecisionModel:
        """
        Runs BacktestEngine.run_backtest (reused, not reimplemented) with an
        explicit engine_override for the baseline (Holt, or Holt-Winters for
        seasonal series) and TimesFM on DECISION_N_CUTOFFS (8) cutoffs over
        the series' recent window (_pick_cutoffs), and decides with
        decide_robust (criterion v4): TimesFM needs a majority of the paired
        cutoffs and a 10% margin on the mean error, a tie goes to the
        baseline, switching away from the `incumbent` needs twice the margin,
        and there is no coverage guard (USE_COVERAGE_GUARD = False).
        From criterion v5 every backtest uses the canonical horizon of the
        series' frequency (_decision_horizon), stored in the decision.
        """
        # Seasonal series (3.0a detector, on the full fetched history) are
        # compared against Holt-Winters with the seasonal MASE: against plain
        # Holt, TimesFM would be beating a baseline that loses even to the
        # seasonal naive (3.0d).
        seasonal = AutoDiscoveryEngine._series_is_seasonal(series_id, is_macro)
        if seasonal:
            from backend.services.forecast_engine import HoltWintersForecastEngine
            baseline_engine, baseline_name, metric = HoltWintersForecastEngine(), "holt_winters", "mase_seasonal"
        else:
            baseline_engine, baseline_name, metric = DampedHoltForecastEngine(), "holt", "mase"

        # Availability is checked ONCE up front: if the real model never
        # loaded, there's no point running the mini-backtest against it at all
        # (every cutoff would just be Holt vs Holt). A loaded model can still
        # fail on a given cutoff and answer with Holt internally; that shows up
        # per cutoff as BacktestResponse.is_fallback, handled in the loop.
        timesfm_engine = _available_timesfm_engine()

        horizon = AutoDiscoveryEngine._decision_horizon(series_id, is_macro)
        cutoffs = AutoDiscoveryEngine._pick_cutoffs(series_id, is_macro)
        if not cutoffs:
            # Raised instead of caching mean([]) = NaN as a "holt" decision: that
            # row would also have mase_timesfm=None, which _is_stale reads as
            # "TimesFM unavailable" and would re-run on every request.
            raise ValueError(f"No hay historia suficiente para ningún cutoff del mini-backtest de {series_id}")

        holt_mases, holt_coverages, holt_maes = [], [], []
        # Paired results, only for cutoffs where TimesFM really ran: comparing
        # TimesFM's mean over some cutoffs against Holt's over all of them
        # would not be the same test.
        paired_holt_mases, paired_holt_coverages, paired_holt_maes = [], [], []
        tfm_mases, tfm_coverages, tfm_maes = [], [], []
        tfm_failed_cutoffs = 0
        baseline_skipped = 0
        # 2.10: the metric is undefined on some cutoff (zero scale: the series
        # didn't move in that training window). Then the whole series is
        # decided on the paired MAE, which is always defined and, within one
        # series, in the same units on every cutoff. Per cutoff both engines
        # share the scale, so wins/losses are the same as with the MASE; only
        # the margin on the mean changes. Dropping those cutoffs instead would
        # lose pairs and could leave fewer than MIN_PAIRED_CUTOFFS.
        metric_undefined = False

        for cutoff_date in cutoffs:
            try:
                holt_res = BacktestEngine.run_backtest(
                    series_id=series_id, cutoff_date=cutoff_date, horizon=horizon,
                    confidence=GUARD_INTERVAL_LEVEL, is_macro=is_macro, engine_override=baseline_engine,
                )
            except NotSeasonalError:
                # Holt-Winters refuses a training window the detector doesn't
                # find seasonal (e.g. an early cutoff): skip it for both engines.
                baseline_skipped += 1
                continue
            base_metric = getattr(holt_res.metrics, metric)
            if base_metric is None and metric in getattr(holt_res.metrics, "undefined", {}):
                metric_undefined = True
            elif base_metric is None:
                # mase_seasonal is None when this training window isn't seasonal.
                baseline_skipped += 1
                continue
            holt_mases.append(base_metric)
            holt_maes.append(getattr(holt_res.metrics, "mae", None))
            holt_coverages.append(holt_res.interval_coverage)

            if timesfm_engine is not None:
                tfm_res = BacktestEngine.run_backtest(
                    series_id=series_id, cutoff_date=cutoff_date, horizon=horizon,
                    confidence=GUARD_INTERVAL_LEVEL, is_macro=is_macro, engine_override=timesfm_engine,
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
                levels = (holt_res.interval_level, tfm_res.interval_level)
                if any(lv is None or abs(lv - GUARD_INTERVAL_LEVEL) > 1e-9 for lv in levels):
                    # Comparing coverages of intervals at different nominal
                    # levels is meaningless; fail the mini-backtest instead.
                    raise ValueError(
                        f"Niveles de intervalo distintos al del guard ({GUARD_INTERVAL_LEVEL}): "
                        f"Holt {levels[0]}, TimesFM {levels[1]}"
                    )
                tfm_metric = getattr(tfm_res.metrics, metric)
                if tfm_metric is None and metric in getattr(tfm_res.metrics, "undefined", {}):
                    metric_undefined = True
                elif tfm_metric is None:
                    continue
                tfm_mases.append(tfm_metric)
                tfm_maes.append(getattr(tfm_res.metrics, "mae", None))
                tfm_coverages.append(tfm_res.interval_coverage)
                paired_holt_mases.append(base_metric)
                paired_holt_maes.append(getattr(holt_res.metrics, "mae", None))
                paired_holt_coverages.append(holt_res.interval_coverage)

        if metric_undefined:
            metric = "mae"
            holt_mases, paired_holt_mases, tfm_mases = holt_maes, paired_holt_maes, tfm_maes

        if not holt_mases:
            raise ValueError(
                f"Ningún cutoff utilizable para {baseline_name} en el mini-backtest de {series_id} "
                f"({baseline_skipped} descartados)"
            )

        mean_mase_tfm = None
        if tfm_mases:
            engine_choice, _ = decide_robust(
                baseline_name, paired_holt_mases, tfm_mases, paired_holt_coverages, tfm_coverages,
                margin=DECISION_MARGIN, alpha=DECISION_ALPHA, min_paired=MIN_PAIRED_CUTOFFS,
                guard=USE_COVERAGE_GUARD, incumbent=incumbent, hysteresis_factor=HYSTERESIS_FACTOR,
            )
            mean_mase_holt = float(np.mean(paired_holt_mases))
            mean_mase_tfm = float(np.mean(tfm_mases))
        else:
            # TimesFM unavailable, or it fell back on every cutoff: baseline alone.
            engine_choice = baseline_name
            mean_mase_holt = float(np.mean(holt_mases))

        return EngineDecisionModel(
            series_id=series_id,
            engine_choice=engine_choice,
            evaluated_at=datetime.now(timezone.utc),
            mase_holt=mean_mase_holt,
            mase_timesfm=mean_mase_tfm,
            n_points_at_evaluation=n_points,
            timesfm_failed_cutoffs=tfm_failed_cutoffs if timesfm_engine is not None else None,
            criteria_version=AUTO_DISCOVERY_CRITERIA_VERSION,
            baseline_engine=baseline_name,
            metric=metric,
            baseline_skipped_cutoffs=baseline_skipped,
            horizon=horizon,
        )

    @staticmethod
    def _load_points(series_id: str, is_macro: bool) -> list:
        """The series' history, via the same fetchers the backtest uses (their
        in-memory cache makes the second call free)."""
        if is_macro:
            from backend.services.data_fetcher import FREDDataFetcher
            data = FREDDataFetcher().get_series(series_id)
        else:
            from backend.services.data_fetcher import MarketDataFetcher
            data = MarketDataFetcher.get_history(series_id, period="5y")
        return sorted(data.points, key=lambda p: p.timestamp)

    @staticmethod
    def _series_is_seasonal(series_id: str, is_macro: bool) -> bool:
        from backend.services.seasonality import detect_seasonality
        return detect_seasonality(AutoDiscoveryEngine._load_points(series_id, is_macro)).is_seasonal

    @staticmethod
    def _decision_horizon(series_id: str, is_macro: bool) -> int:
        """Horizon the mini-backtest evaluates at (criterion v5): the canonical
        horizon of the series' frequency, inferred from its dates."""
        from backend.services.horizons import canonical_horizon, series_frequency
        points = AutoDiscoveryEngine._load_points(series_id, is_macro)
        return canonical_horizon(series_frequency([p.timestamp for p in points]))

    @staticmethod
    def _pick_cutoffs(series_id: str, is_macro: bool) -> list:
        """DECISION_N_CUTOFFS cutoff dates evenly spaced over the series' recent
        window (RECENT_WINDOW by frequency), each leaving the decision horizon
        (_decision_horizon) of points for evaluation."""
        from backend.services.seasonality import infer_frequency
        sorted_points = AutoDiscoveryEngine._load_points(series_id, is_macro)
        window = RECENT_WINDOW.get(infer_frequency([p.timestamp for p in sorted_points]), RECENT_WINDOW_DEFAULT)
        horizon = AutoDiscoveryEngine._decision_horizon(series_id, is_macro)
        required = min_history_for_decision(horizon)
        if len(sorted_points) < required:
            raise InsufficientHistoryError(series_id, len(sorted_points), required, horizon)
        idx = recent_cutoff_indices(len(sorted_points), DECISION_N_CUTOFFS, window, horizon=horizon)
        return [sorted_points[i].timestamp for i in idx]
