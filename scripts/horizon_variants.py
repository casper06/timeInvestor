"""
Mini-backtest horizon by frequency (item 2.3b of docs/PLAN.md).

Keeps criterion v4 fixed (auto_discovery.decide_robust: recent window by
frequency, 8 cutoffs, majority + 10% margin, >= 7 pairs, hysteresis x2, no
guard) and varies ONLY the evaluation horizon, per frequency. Same metrics as
scripts/decision_variants.py, plus how many practically independent
(non-overlapping) evaluation windows each horizon leaves.

Regret (2.3c): what a wrong decision COSTS, not just how often it differs.
For each 8-cutoff decision, the relative extra error of the chosen engine
against the best one, measured on the grid cutoffs that were NOT used to
decide (held out), so it isn't scored on the data that made the decision.

    python scripts/horizon_variants.py --replay data/snapshots/holt_coverage_2026-09-26.json --out results.json [--series A,B] [--horizons "monthly=12,6"]
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


def holdout_regret(err_base: dict, err_tfm: dict, grid, subset, choice: str, baseline: str):
    """E_chosen(H) / min(E_base(H), E_tfm(H)) - 1, where H = grid cutoffs not
    in `subset` on which BOTH engines have an error (paired), E = mean error.
    None if H has no paired cutoff."""
    used = set(subset)
    held = [i for i in grid if i not in used and err_base.get(i) is not None and err_tfm.get(i) is not None]
    if not held:
        return None
    e_base = float(np.mean([err_base[i] for i in held]))
    e_tfm = float(np.mean([err_tfm[i] for i in held]))
    best = min(e_base, e_tfm)
    chosen = e_tfm if choice == "timesfm" else e_base
    return chosen / best - 1.0 if best > 0 else 0.0


def _errors(ev, grid, baseline, metric):
    """Per-cutoff errors of each engine on the grid (None = refused/fallback)."""
    eb, et = {}, {}
    for i in grid:
        b = ev.run(i, baseline)
        eb[i] = None if b.get("refused") or b.get(metric) is None else b[metric]
        t = ev.run(i, "timesfm")
        et[i] = None if t.get("fallback") or t.get(metric) is None else t[metric]
    return eb, et


def _grid_summary(eb, et):
    """Head-to-head on the paired grid cutoffs: mean error and wins per engine."""
    paired = [i for i in eb if eb[i] is not None and et.get(i) is not None]
    return {
        "n_paired": len(paired),
        "mean_base": float(np.mean([eb[i] for i in paired])) if paired else None,
        "mean_tfm": float(np.mean([et[i] for i in paired])) if paired else None,
        "wins_base": sum(eb[i] < et[i] for i in paired),
        "wins_tfm": sum(et[i] < eb[i] for i in paired),
        "ties": sum(et[i] == eb[i] for i in paired),
    }


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
        eb, et = _errors(ev, grid, baseline, metric)
        regrets = [holdout_regret(eb, et, grid, s, d, baseline) for s, d in zip(subsets, decisions)]
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
            "regrets": [None if r is None else round(r, 6) for r in regrets],
            "grid": _grid_summary(eb, et),
        }
    return out


def detail(sid, entry, horizons):
    """Per-cutoff errors of both engines on the 24-cutoff grid, per horizon."""
    from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
    from backend.services import auto_discovery as ad
    from backend.services.seasonality import detect_seasonality, infer_frequency
    is_macro = entry["category"] == "fred"
    dates = sorted(entry["values"])
    pts = [TimeSeriesPoint(timestamp=d, value=entry["values"][d]) for d in dates]
    series = TimeSeriesData(id=sid, name=sid, type="macro" if is_macro else "equity", unit="", points=pts, source="live")
    window = ad.RECENT_WINDOW.get(infer_frequency(dates), ad.RECENT_WINDOW_DEFAULT)
    seasonal = detect_seasonality(pts).is_seasonal
    baseline, metric = ("holt_winters", "mase_seasonal") if seasonal else ("holt", "mase")
    out = {"baseline": baseline, "metric": metric, "horizons": {}}
    for h in horizons:
        ev = _Evaluator(sid, series, is_macro, horizon=h)
        grid = ad.recent_cutoff_indices(len(pts), N_GRID, window, horizon=h)
        eb, et = _errors(ev, grid, baseline, metric)
        out["horizons"][str(h)] = {
            "cutoffs": [{"date": dates[i], "base": eb[i], "timesfm": et[i]} for i in grid],
            "summary": _grid_summary(eb, et),
        }
    return out


def category(entry) -> str:
    if entry["category"] == "fred":
        return "FRED estacional" if entry["baseline"] == "holt_winters" else "FRED SA"
    return {"accion": "Acciones", "etf": "ETFs"}.get(entry["category"], entry["category"])


def regret_table(res) -> list:
    """Rows (category, horizon, n, mean, median, p90) pooling every decision
    of every series of the category; regrets in percentage points."""
    pooled = {}
    for entry in res["series"].values():
        for h, row in entry["rows"].items():
            if "regrets" in row:
                pooled.setdefault((category(entry), int(h)), []).extend(r for r in row["regrets"] if r is not None)
    rows = []
    for (cat, h), rs in sorted(pooled.items()):
        a = 100 * np.array(rs)
        rows.append((cat, h, len(rs), float(a.mean()), float(np.median(a)), float(np.percentile(a, 90))))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--summary", default="", help="solo imprime la tabla de arrepentimiento de un JSON ya generado")
    ap.add_argument("--detail", default="", help="serie: errores por cutoff de la grilla (usa --horizons monthly=...)")
    ap.add_argument("--replay")
    ap.add_argument("--out")
    ap.add_argument("--series", default="")
    ap.add_argument("--horizons", default="", help="p. ej. monthly=12,6,3;daily=60 (reemplaza HORIZONS)")
    args = ap.parse_args()
    if args.summary:
        for cat, h, n, mean, med, p90 in regret_table(json.loads(Path(args.summary).read_text(encoding="utf-8"))):
            print(f"{cat:16} h={h:3d} n={n:5d} media={mean:6.2f} mediana={med:6.2f} p90={p90:6.2f} (pp)")
        return
    if not (args.replay and args.out):
        ap.error("--replay y --out son obligatorios salvo con --summary")
    for part in filter(None, args.horizons.split(";")):
        kind, hs = part.split("=")
        HORIZONS[kind] = [int(h) for h in hs.split(",")]
    from backend.services.forecast_engine import TimesFMForecastEngine
    if not TimesFMForecastEngine.is_available():
        print("ERROR: TimesFM no disponible; no se simula.", file=sys.stderr)
        sys.exit(2)
    raw = Path(args.replay).read_bytes()
    snap = json.loads(raw)
    if args.detail:
        entry = snap["series"][args.detail]
        kind = "monthly" if entry["category"] == "fred" else "daily"
        res = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(), args.detail: detail(args.detail, entry, HORIZONS[kind])}
        Path(args.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
        print("escrito", args.out)
        return
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
