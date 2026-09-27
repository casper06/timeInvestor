"""
Mini-backtest horizon by frequency (item 2.3b of docs/PLAN.md).

Keeps criterion v4 fixed (auto_discovery.decide_robust: recent window by
frequency, 8 cutoffs, majority + 10% margin, >= 7 pairs, hysteresis x2, no
guard) and varies ONLY the evaluation horizon, per frequency. Same metrics as
scripts/decision_variants.py, plus how many practically independent
(non-overlapping) evaluation windows each horizon leaves.

    python scripts/horizon_variants.py --replay data/snapshots/holt_coverage_2026-09-26.json --out results.json [--series A,B]
"""
import argparse
import hashlib
import itertools
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision_stability import _Evaluator  # noqa: E402

HORIZONS = {"daily": [30, 60], "monthly": [30, 24, 12]}
N_GRID = 24
N_RANDOM_SUBSETS = 400
ENDS = {"daily": list(range(0, 61, 10)), "monthly": list(range(0, 13, 2))}


def _independent(indices, horizon):
    """Greedy count of evaluation windows [i+1, i+horizon] that don't overlap."""
    count, last_end = 0, -1
    for i in sorted(indices):
        if i + 1 > last_end:
            count += 1
            last_end = i + horizon
    return count


def _decide(ev, indices, baseline, metric, incumbent=None):
    from backend.services import auto_discovery as ad
    pb, pbc, tf, tfc = [], [], [], []
    for i in indices:
        b = ev.run(i, baseline)
        if b.get("refused") or b.get(metric) is None:
            continue
        t = ev.run(i, "timesfm")
        if t["fallback"] or t.get(metric) is None:
            continue
        pb.append(b[metric]); pbc.append(b["cov"]); tf.append(t[metric]); tfc.append(t["cov"])
    choice, _ = ad.decide_robust(baseline, pb, tf, pbc, tfc, margin=ad.DECISION_MARGIN, alpha=ad.DECISION_ALPHA,
                                 min_paired=ad.MIN_PAIRED_CUTOFFS, guard=ad.USE_COVERAGE_GUARD,
                                 incumbent=incumbent, hysteresis_factor=ad.HYSTERESIS_FACTOR)
    return choice


def analyze(sid, entry):
    from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
    from backend.services import auto_discovery as ad
    from backend.services.seasonality import detect_seasonality, infer_frequency
    is_macro = entry["category"] == "fred"
    dates = sorted(entry["values"])
    pts = [TimeSeriesPoint(timestamp=d, value=entry["values"][d]) for d in dates]
    series = TimeSeriesData(id=sid, name=sid, type="macro" if is_macro else "equity", unit="", points=pts, source="live")
    freq = infer_frequency(dates)
    kind = "monthly" if freq == "monthly" else "daily"
    window = ad.RECENT_WINDOW.get(freq, ad.RECENT_WINDOW_DEFAULT)
    n = len(pts)
    seasonal = detect_seasonality(pts).is_seasonal
    baseline, metric = ("holt_winters", "mase_seasonal") if seasonal else ("holt", "mase")
    out = {"category": entry["category"], "kind": kind, "baseline": baseline, "rows": {}}
    for h in HORIZONS[kind]:
        ev = _Evaluator(sid, series, is_macro, horizon=h)
        grid = ad.recent_cutoff_indices(n, N_GRID, window, horizon=h)
        ref = _decide(ev, grid, baseline, metric)
        rng = random.Random(f"{sid}-2.3b-{h}")
        subsets = [tuple(sorted(rng.sample(grid, ad.DECISION_N_CUTOFFS))) for _ in range(N_RANDOM_SUBSETS)]
        decisions = [_decide(ev, list(s), baseline, metric) for s in subsets]
        choices, choices_h, inc = [], [], None
        for off in ENDS[kind]:
            idx = ad.recent_cutoff_indices(n - off, ad.DECISION_N_CUTOFFS, window, horizon=h)
            choices.append(_decide(ev, idx, baseline, metric))
            inc = _decide(ev, idx, baseline, metric, incumbent=inc)
            choices_h.append(inc)
        latest = ad.recent_cutoff_indices(n, ad.DECISION_N_CUTOFFS, window, horizon=h)
        t0 = time.perf_counter()
        ev2 = _Evaluator(sid, series, is_macro, horizon=h)
        for i in latest:
            ev2.run(i, baseline); ev2.run(i, "timesfm")
        out["rows"][str(h)] = {
            "reference": ref,
            "disagree_pct": 100.0 * sum(d != ref for d in decisions) / len(decisions),
            "base_pct": 100.0 * sum(d == baseline for d in decisions) / len(decisions),
            "flips": sum(a != b for a, b in zip(choices, choices[1:])),
            "flips_hyst": sum(a != b for a, b in zip(choices_h, choices_h[1:])),
            "n_windows": len(ENDS[kind]),
            "latest": choices_h[-1],
            "latest_cutoffs": [dates[i] for i in latest],
            "independent_of_8": _independent(latest, h),
            "latency_s": time.perf_counter() - t0,
            "tfm_fallbacks": sum(1 for (i, e), r in ev.cache.items() if e == "timesfm" and r.get("fallback")),
        }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--series", default="")
    args = ap.parse_args()
    from backend.services.forecast_engine import TimesFMForecastEngine
    if not TimesFMForecastEngine.is_available():
        print("ERROR: TimesFM no disponible; no se simula.", file=sys.stderr)
        sys.exit(2)
    raw = Path(args.replay).read_bytes()
    snap = json.loads(raw)
    wanted = [s for s in args.series.split(",") if s] or list(snap["series"])
    res = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(), "series": {}}
    for sid in wanted:
        t0 = time.perf_counter()
        res["series"][sid] = analyze(sid, snap["series"][sid])
        print(f"{sid}: {time.perf_counter() - t0:.0f}s", flush=True)
    Path(args.out).write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print("escrito", args.out)


if __name__ == "__main__":
    main()
