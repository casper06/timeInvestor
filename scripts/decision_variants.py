"""
Variants of the auto-discovery decision rule (item 2.3 of docs/PLAN.md),
measured on the 2.5 snapshot with production code:
auto_discovery.decide_robust / choose_engine / recent_cutoff_indices /
pick_cutoff_indices, and scripts/decision_stability.py's evaluator
(BacktestEngine.run_backtest at the guard's 80% level, TimesFM real).

    python scripts/decision_variants.py --replay data/snapshots/holt_coverage_2026-09-26.json --out results.json [--series A,B]

For each variant and series:
- reference: the variant's rule on a dense grid of 24 cutoffs over the
  variant's own window (full history or the recent window);
- disagree_pct: K-cutoff decisions (all C(24,3) for K=3; 400 seeded random
  subsets for K=5 and 8) that differ from that reference;
- base_pct: share of those decisions that end in the baseline;
- flips: changes of the decision production would make with the data ending
  0..60 points (daily, step 10) or 0..12 months (monthly, step 2) earlier,
  with the variant's own cutoffs; flips_hyst: same, with hysteresis (the
  previous window's decision is the incumbent);
- latency: measured seconds of the K cutoff pairs (baseline + TimesFM) of
  the latest window, per series (first request, model already loaded).
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

N_GRID = 24
K_VALUES = [3, 5, 8]
WINDOWS = {"daily": 504, "monthly": 120}   # recent window: 2 years / 10 years
ENDS = {"daily": list(range(0, 61, 10)), "monthly": list(range(0, 13, 2))}
N_RANDOM_SUBSETS = 400
HYSTERESIS_FACTOR = 2.0

CONSISTENCY = {"media": "mean", "mayoria": None, "signo10": 0.10, "signo05": 0.05}
MARGINS = [0.0, 0.05, 0.10]
GUARDS = [True, False]


def _pairs(ev, indices, baseline, metric):
    pb, pbc, tf, tfc = [], [], [], []
    for i in indices:
        b = ev.run(i, baseline)
        if b.get("refused") or b.get(metric) is None:
            continue
        t = ev.run(i, "timesfm")
        if t["fallback"] or t.get(metric) is None:
            continue
        pb.append(b[metric]); pbc.append(b["cov"]); tf.append(t[metric]); tfc.append(t["cov"])
    return pb, pbc, tf, tfc


def _decide(variant, ev, indices, baseline, metric, incumbent=None):
    from backend.services.auto_discovery import choose_engine, decide_robust
    pb, pbc, tf, tfc = _pairs(ev, indices, baseline, metric)
    cons, margin, guard = variant["consistency"], variant["margin"], variant["guard"]
    if cons == "mean":  # mean only, like the current rule (strictly lower +/- margin)
        if not tf:
            return baseline
        if margin == 0.0 and guard:
            choice = choose_engine(baseline, pb, pbc, tf, tfc)
        else:
            ok_guard = (not guard) or (np.mean(pbc) - np.mean(tfc) <= 30.0)
            choice = "timesfm" if (np.mean(tf) <= (1 - margin) * np.mean(pb) and np.mean(tf) < np.mean(pb) and ok_guard) else baseline
        return choice
    choice, _ = decide_robust(baseline, pb, tf, pbc, tfc, margin=margin, alpha=cons,
                              min_paired=variant["min_paired"], guard=guard,
                              incumbent=incumbent, hysteresis_factor=HYSTERESIS_FACTOR)
    return choice


def _grid(n, kind, window_name):
    from backend.services.auto_discovery import MINI_BACKTEST_HORIZON, recent_cutoff_indices
    if window_name == "reciente":
        return recent_cutoff_indices(n, N_GRID, WINDOWS[kind])
    lo, hi = max(30, MINI_BACKTEST_HORIZON * 2) - 1, n - 1 - MINI_BACKTEST_HORIZON
    return sorted({int(round(x)) for x in np.linspace(lo, hi, N_GRID)})


def _cutoffs(n, kind, window_name, k):
    from backend.services.auto_discovery import recent_cutoff_indices
    from backend.services import auto_discovery as ad
    if window_name == "reciente":
        return recent_cutoff_indices(n, k, WINDOWS[kind])
    lo, hi = max(30, ad.MINI_BACKTEST_HORIZON * 2) - 1, n - 1 - ad.MINI_BACKTEST_HORIZON
    return sorted({int(round(x)) for x in np.linspace(lo, hi, k)})


def variants():
    out = []
    for window_name in ("toda", "reciente"):
        for k in K_VALUES:
            for cname, cons in CONSISTENCY.items():
                for margin in MARGINS:
                    for guard in GUARDS:
                        out.append({"window": window_name, "k": k, "consistency": cons, "cname": cname,
                                    "margin": margin, "guard": guard, "min_paired": max(3, k - 1)})
    return out


def analyze(sid, entry):
    from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
    from backend.services.seasonality import detect_seasonality, infer_frequency
    is_macro = entry["category"] == "fred"
    dates = sorted(entry["values"])
    pts = [TimeSeriesPoint(timestamp=d, value=entry["values"][d]) for d in dates]
    series = TimeSeriesData(id=sid, name=sid, type="macro" if is_macro else "equity", unit="", points=pts, source="live")
    ev = _Evaluator(sid, series, is_macro)
    n = len(pts)
    kind = "monthly" if infer_frequency(dates) == "monthly" else "daily"
    seasonal = detect_seasonality(pts).is_seasonal
    baseline, metric = ("holt_winters", "mase_seasonal") if seasonal else ("holt", "mase")

    # latency of the latest window's K pairs (first request, model loaded)
    latency = {}
    for w in ("toda", "reciente"):
        for k in K_VALUES:
            idx = _cutoffs(n, kind, w, k)
            fresh = [i for i in idx if (i, "timesfm") not in ev.cache]
            t0 = time.perf_counter()
            for i in idx:
                ev.run(i, baseline); ev.run(i, "timesfm")
            latency[f"{w}_k{k}"] = {"seconds": time.perf_counter() - t0, "fresh_cutoffs": len(fresh), "k": len(idx)}

    rng = random.Random(f"{sid}-2.3")
    rows = []
    for v in variants():
        grid = _grid(n, kind, v["window"])
        ref = _decide(v, ev, grid, baseline, metric)
        if v["k"] == 3:
            subsets = list(itertools.combinations(grid, 3))
        else:
            subsets = [tuple(sorted(rng.sample(grid, v["k"]))) for _ in range(N_RANDOM_SUBSETS)]
        decisions = [_decide(v, ev, list(s), baseline, metric) for s in subsets]
        choices, choices_h, inc = [], [], None
        for off in ENDS[kind]:
            n_e = n - off
            idx = _cutoffs(n_e, kind, v["window"], v["k"])
            choices.append(_decide(v, ev, idx, baseline, metric))
            if v["consistency"] == "mean":
                choices_h.append(choices[-1])
            else:
                inc = _decide(v, ev, idx, baseline, metric, incumbent=inc)
                choices_h.append(inc)
        rows.append({**{k: v[k] for k in ("window", "k", "cname", "margin", "guard")},
                     "reference": ref,
                     "disagree_pct": 100.0 * sum(d != ref for d in decisions) / len(decisions),
                     "base_pct": 100.0 * sum(d == baseline for d in decisions) / len(decisions),
                     "flips": sum(a != b for a, b in zip(choices, choices[1:])),
                     "flips_hyst": sum(a != b for a, b in zip(choices_h, choices_h[1:])),
                     "latest": choices[0], "latest_hyst": choices_h[-1]})
    return {"category": entry["category"], "kind": kind, "baseline": baseline, "n_windows": len(ENDS[kind]),
            "latency": latency, "rows": rows,
            "tfm_fallbacks": sum(1 for (i, e), r in ev.cache.items() if e == "timesfm" and r.get("fallback"))}


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
