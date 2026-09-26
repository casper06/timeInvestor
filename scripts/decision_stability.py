"""
How much do auto-discovery decisions oscillate? (item 2.2 of docs/PLAN.md)

Measures the CURRENT rule, reusing production code, not a copy of it:
auto_discovery.choose_engine (TimesFM if its mean metric is strictly lower and
its coverage gap is <= 30 pp), auto_discovery.pick_cutoff_indices (3 evenly
spaced cutoffs), BacktestEngine.run_backtest at the guard's 80% level, and
the 3.0f baseline (Holt-Winters with the seasonal MASE for seasonal series,
Holt with the 1-step MASE otherwise).

    python scripts/decision_stability.py --replay data/snapshots/holt_coverage_2026-09-26.json --out results.json

Per series (snapshot, no downloads, no DB):
A. Cutoff placement. A dense grid of 24 cutoffs is evaluated once per engine.
   The reference decision uses all 24; the rule is then applied to EVERY
   3-cutoff subset of the grid, and the share that disagrees with the
   reference is reported. That's the placement noise of a 3-cutoff decision.
B. Nearby windows. The decision production would make with the data ending
   0, 5, ..., 60 points earlier (daily) or 0..12 months earlier (monthly),
   each time with production's own 3 cutoffs: flips between consecutive end
   dates, and how many distinct decisions.
C. Near ties: relative gap mean(TimesFM)/mean(baseline) - 1 of each decision;
   share within +/-5% and +/-10% (input for 2.3's margin).
D. Guard effect: how often the coverage guard changes the decision vs. the
   metric alone.

TimesFM must run with its real weights; on a cutoff where it falls back to
Holt, that cutoff is dropped for both engines, exactly as production does,
and counted. Backtest results depend only on the cutoff (training up to it,
evaluation on the next 30 points), so each cutoff is evaluated once.
"""
import argparse
import hashlib
import itertools
import json
import platform
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

N_GRID = 24
END_OFFSETS = {"daily": list(range(0, 61, 5)), "monthly": list(range(0, 13))}


def _fail(message: str) -> "NoReturn":
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


class _Evaluator:
    """Per-cutoff backtests of one series, cached by (cutoff index, engine)."""

    def __init__(self, sid: str, series, is_macro: bool):
        from backend.services import backtest_engine
        self.sid, self.series, self.is_macro = sid, series, is_macro
        self.points = sorted(series.points, key=lambda p: p.timestamp)
        self._bt = backtest_engine
        self.cache = {}

    def run(self, idx: int, engine_name: str):
        key = (idx, engine_name)
        if key in self.cache:
            return self.cache[key]
        from backend.services import auto_discovery as ad
        from backend.services.backtest_engine import BacktestEngine
        from backend.services.forecast_engine import (
            DampedHoltForecastEngine, HoltWintersForecastEngine, NotSeasonalError, TimesFMForecastEngine)
        engine = {"holt": DampedHoltForecastEngine, "holt_winters": HoltWintersForecastEngine,
                  "timesfm": TimesFMForecastEngine}[engine_name]()
        series = self.series

        class _Market:
            @staticmethod
            def get_history(*a, **k):
                return series

        class _Fred:
            SERIES_CATALOG = self._bt.FREDDataFetcher.SERIES_CATALOG

            def get_series(self, *a, **k):
                return series

        real = (self._bt.MarketDataFetcher, self._bt.FREDDataFetcher)
        self._bt.MarketDataFetcher, self._bt.FREDDataFetcher = _Market, _Fred
        try:
            res = BacktestEngine.run_backtest(
                series_id=self.sid, cutoff_date=self.points[idx].timestamp, horizon=ad.MINI_BACKTEST_HORIZON,
                confidence=ad.GUARD_INTERVAL_LEVEL, is_macro=self.is_macro, engine_override=engine)
            out = {"mase": res.metrics.mase, "mase_seasonal": res.metrics.mase_seasonal,
                   "cov": res.interval_coverage, "fallback": bool(res.is_fallback), "refused": False,
                   "level": res.interval_level}
        except NotSeasonalError:
            out = {"refused": True}
        finally:
            self._bt.MarketDataFetcher, self._bt.FREDDataFetcher = real
        self.cache[key] = out
        return out


def _decide(ev: _Evaluator, indices: list, baseline: str, metric: str) -> dict:
    """Production's rule on these cutoffs: pairs, drops fallback/refused ones."""
    from backend.services.auto_discovery import choose_engine
    pb, pbc, tf, tfc = [], [], [], []
    dropped = 0
    for i in indices:
        b = ev.run(i, baseline)
        if b.get("refused") or b.get(metric) is None:
            dropped += 1
            continue
        t = ev.run(i, "timesfm")
        if t["fallback"] or t.get(metric) is None:
            dropped += 1
            continue
        pb.append(b[metric]); pbc.append(b["cov"]); tf.append(t[metric]); tfc.append(t["cov"])
    if not tf:
        return {"choice": baseline, "paired": 0, "dropped": dropped, "rel_gap": None, "metric_only": baseline}
    choice = choose_engine(baseline, pb, pbc, tf, tfc)
    metric_only = "timesfm" if np.mean(tf) < np.mean(pb) else baseline
    return {"choice": choice, "metric_only": metric_only, "paired": len(tf), "dropped": dropped,
            "rel_gap": float(np.mean(tf) / np.mean(pb) - 1.0),
            "cov_gap": float(np.mean(pbc) - np.mean(tfc))}


def _near_tie_shares(gaps: list) -> dict:
    g = np.array([x for x in gaps if x is not None])
    if not len(g):
        return {"n": 0, "within_5pct": None, "within_10pct": None}
    return {"n": int(len(g)), "within_5pct": float(np.mean(np.abs(g) <= 0.05) * 100),
            "within_10pct": float(np.mean(np.abs(g) <= 0.10) * 100)}


def analyze(sid: str, entry: dict) -> dict:
    from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
    from backend.services import auto_discovery as ad
    from backend.services.seasonality import detect_seasonality, infer_frequency

    is_macro = entry["category"] == "fred"
    dates = sorted(entry["values"])
    pts = [TimeSeriesPoint(timestamp=d, value=entry["values"][d]) for d in dates]
    series = TimeSeriesData(id=sid, name=sid, type="macro" if is_macro else "equity", unit="",
                            points=pts, source="live")
    ev = _Evaluator(sid, series, is_macro)
    n = len(pts)
    freq = infer_frequency(dates)
    kind = "monthly" if freq == "monthly" else "daily"

    seasonal_full = detect_seasonality(pts).is_seasonal
    baseline, metric = ("holt_winters", "mase_seasonal") if seasonal_full else ("holt", "mase")

    # A. placement noise on a dense grid
    lo, hi = max(30, ad.MINI_BACKTEST_HORIZON * 2) - 1, n - 1 - ad.MINI_BACKTEST_HORIZON
    grid = sorted({int(round(x)) for x in np.linspace(lo, hi, N_GRID)})
    reference = _decide(ev, grid, baseline, metric)
    subsets = [_decide(ev, list(c), baseline, metric) for c in itertools.combinations(grid, 3)]
    disagree = sum(s["choice"] != reference["choice"] for s in subsets)
    tfm_share = sum(s["choice"] == "timesfm" for s in subsets)

    # B. nearby windows, production's own cutoffs
    windows = []
    for off in END_OFFSETS[kind]:
        n_e = n - off
        idx = ad.pick_cutoff_indices(n_e)
        seas = detect_seasonality(pts[:n_e]).is_seasonal
        b, m = ("holt_winters", "mase_seasonal") if seas else ("holt", "mase")
        d = _decide(ev, idx, b, m)
        windows.append({"end": dates[n_e - 1], "offset": off, "cutoffs": [dates[i] for i in idx],
                        "baseline": b, **d})
    choices = [w["choice"] for w in windows]
    flips = sum(a != b for a, b in zip(choices, choices[1:]))

    tfm_fallbacks = sum(1 for (i, e), r in ev.cache.items() if e == "timesfm" and r.get("fallback"))
    return {
        "category": entry["category"], "frequency": freq, "n_points": n, "seasonal": seasonal_full,
        "baseline": baseline, "metric": metric,
        "A_placement": {"grid_size": len(grid), "reference": reference, "subsets": len(subsets),
                        "disagree_with_reference_pct": 100.0 * disagree / len(subsets),
                        "timesfm_chosen_pct": 100.0 * tfm_share / len(subsets),
                        "near_ties": _near_tie_shares([s["rel_gap"] for s in subsets]),
                        "guard_changed_pct": 100.0 * sum(s["choice"] != s["metric_only"] for s in subsets) / len(subsets)},
        "B_windows": {"windows": windows, "flips": flips, "distinct": sorted(set(choices)),
                      "near_ties": _near_tie_shares([w["rel_gap"] for w in windows]),
                      "guard_changed": sum(w["choice"] != w["metric_only"] for w in windows)},
        "timesfm_fallback_cutoffs": tfm_fallbacks,
        "cutoffs_evaluated": len({i for i, _ in ev.cache}),
    }


def replay(snapshot_path: str, out_path: str) -> None:
    from backend.services.forecast_engine import TimesFMForecastEngine
    if not TimesFMForecastEngine.is_available():
        _fail("TimesFM no está disponible (pesos o USE_REAL_TIMESFM). No se simula: se frena.")
    raw = Path(snapshot_path).read_bytes()
    snap = json.loads(raw)
    result = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(), "python": platform.python_version(),
              "series": {}}
    for sid, entry in snap["series"].items():
        r = analyze(sid, entry)
        result["series"][sid] = r
        a, b = r["A_placement"], r["B_windows"]
        print(f"{sid:11} {r['frequency']:7} base={r['baseline']:12} ref={a['reference']['choice']:12} "
              f"desacuerdo3={a['disagree_with_reference_pct']:5.1f}% tfm3={a['timesfm_chosen_pct']:5.1f}% "
              f"flips={b['flips']}/{len(b['windows']) - 1} distintas={b['distinct']}")
    Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"escrito {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--replay", required=True, metavar="SNAPSHOT")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    replay(args.replay, args.out)


if __name__ == "__main__":
    main()
