"""
Forecasting capability by FRED category (item 3.5 of docs/PLAN.md), with the
re-evaluation of v5 and of Holt variant C. Everything follows the
pre-registration in docs/PLAN.md (commit 2c07372); nothing here is chosen
after seeing results.

    # 1. snapshot (downloads, with sha256):
    python scripts/fred_category_benchmark.py --download --selection docs/results/fred_category_selection_2026-09-27.json --snapshot data/snapshots/fred_categories_2026-09-27.json
    # 2. measurement (TimesFM with real weights; aborts on any TimesFM fallback):
    python scripts/fred_category_benchmark.py --replay data/snapshots/fred_categories_2026-09-27.json --out docs/results/fred_category_benchmark_2026-09-27.json
    # 3. tables from a result:
    python scripts/fred_category_benchmark.py --summary docs/results/fred_category_benchmark_2026-09-27.json
"""
import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

ALPHA = 0.05
N_GRID = 24
V4_HORIZON = 30
REGRET_CAP = 1.0            # 100 pp (criteria db4fcdb / 0ba851a)
TIE_PP, CATASTROPHIC_PP = 2.0, 25.0
C_MASE_FACTOR, C_COVERAGE_PP, NOMINAL = 1.02, 2.0, 80.0
SEASON = {"monthly": 12, "quarterly": 4}


class TimesFMFellBack(RuntimeError):
    pass


# ---------------------------------------------------------------- download

def download(selection_path, snapshot_path):
    from backend.services.data_fetcher import FREDDataFetcher
    raw_sel = Path(selection_path).read_bytes()
    sel = json.loads(raw_sel)
    snap = {"selection_sha256": hashlib.sha256(raw_sel).hexdigest(),
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M"), "series": {}}
    for cat, block in sel["categories"].items():
        for meta in block["series"]:
            data = FREDDataFetcher().get_series(meta["id"])
            if data.source != "live":
                raise SystemExit(f"{meta['id']}: source={data.source}; solo datos reales")
            snap["series"][meta["id"]] = {
                "category": cat, "ya_vista": meta["ya_vista"], "title": meta["title"],
                "seasonal_adjustment": meta["seasonal_adjustment"],
                "values": {p.timestamp: p.value for p in data.points},
            }
            print(meta["id"], len(data.points), data.points[0].timestamp, "->", data.points[-1].timestamp, flush=True)
    raw = json.dumps(snap, indent=1, sort_keys=True).encode("utf-8")
    Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)
    Path(snapshot_path).write_bytes(raw)
    print("snapshot", snapshot_path, "sha256", hashlib.sha256(raw).hexdigest())


# ---------------------------------------------------------------- helpers

def sign_test_p(wins, losses):
    from scipy import stats
    n = wins + losses
    return float(stats.binomtest(wins, n, 0.5, alternative="greater").pvalue) if n else 1.0


def holm(pvals, alpha=ALPHA):
    """Holm step-down: which hypotheses are rejected (same order as input)."""
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    rejected, m = [False] * len(pvals), len(pvals)
    for rank, i in enumerate(order):
        if pvals[i] < alpha / (m - rank):
            rejected[i] = True
        else:
            break
    return rejected


class Run:
    """One series at one horizon: evaluator + grid, TimesFM checked."""

    def __init__(self, sid, series, h, window, extra):
        from decision_stability import _Evaluator
        from backend.services import auto_discovery as ad
        self.ev = _Evaluator(sid, series, True, horizon=h, extra_engines=extra)
        self.grid = ad.recent_cutoff_indices(len(series.points), N_GRID, window, horizon=h)
        self.sid, self.h = sid, h

    def run(self, i, engine):
        r = self.ev.run(i, engine)
        if engine == "timesfm" and r.get("fallback"):
            raise TimesFMFellBack(f"TimesFM cayó a Holt en {self.sid}, h={self.h}, cutoff {i}")
        return r


# ---------------------------------------------------------------- capability

def capability(run, values, seasonal, freq, engines):
    rw, snaive = [], []
    from backend.services.seasonality import seasonal_naive_forecast
    for i in run.grid:
        train, fut = np.array(values[: i + 1]), np.array(values[i + 1: i + 1 + run.h])
        rw.append(float(np.mean(np.abs(fut - train[-1]))))
        if seasonal:
            snaive.append(float(np.mean(np.abs(fut - seasonal_naive_forecast(train, run.h, SEASON[freq])))))
    ref_name, ref = "random_walk", rw
    if seasonal and sum(snaive) < sum(rw):
        ref_name, ref = "naive_estacional", snaive
    k = len(engines)
    out = {"reference_naive": ref_name, "k": k, "engines": {}}
    for eng in engines:
        rows = [run.run(i, eng) for i in run.grid]
        mae = [r["mae"] for r in rows]
        wins = sum(a < b for a, b in zip(mae, ref))
        losses = sum(a > b for a, b in zip(mae, ref))
        p = sign_test_p(wins, losses)
        skill = 1.0 - sum(mae) / sum(ref) if sum(ref) > 0 else None
        out["engines"][eng] = {
            "mae": mae, "wins": wins, "losses": losses, "p": p,
            "skill": skill,
            "skill_vs_rw": 1.0 - sum(mae) / sum(rw) if sum(rw) > 0 else None,
            "skill_vs_snaive": (1.0 - sum(mae) / sum(snaive)) if seasonal and sum(snaive) > 0 else None,
            "coverage": float(np.mean([r["cov"] for r in rows])),
            "nominal": 100.0 * float(np.mean([r["level"] for r in rows])),
            "beats": bool(p < ALPHA / k and skill is not None and skill > 0),
        }
    out["rw_mae"], out["snaive_mae"] = rw, snaive or None
    out["has_capacity"] = any(e["beats"] for e in out["engines"].values())
    return out


# ---------------------------------------------------------------- v5 and C

def decide_like_production(ev, sub, baseline, metric):
    """The v4 rule on these cutoffs. decide_robust raises ZeroDivisionError
    when the baseline's mean error is exactly 0 (an informational ratio,
    rel_gap; seen on DFEDTARU, a step series where Holt's rounded forecast is
    exact). Production's decide() catches it and the series falls to the
    default path (Holt): same here, the baseline, and it's counted."""
    from horizon_variants import _decide
    try:
        return _decide(ev, sub, baseline, metric), False
    except ZeroDivisionError:
        return baseline, True


def capped_regret(eb, et, held_grid, sub, choice):
    """holdout_regret (scripts/horizon_variants.py) capped at REGRET_CAP, with
    one fix: if the best engine's held-out error is exactly 0 and the chosen
    one's isn't, the relative extra error is unbounded (-> the cap), not 0.
    Identical to holdout_regret whenever the best error is > 0."""
    used = set(sub)
    held = [i for i in held_grid if i not in used and eb.get(i) is not None and et.get(i) is not None]
    if not held:
        return None
    e_b = float(np.mean([eb[i] for i in held]))
    e_t = float(np.mean([et[i] for i in held]))
    best, chosen = min(e_b, e_t), (e_t if choice == "timesfm" else e_b)
    r = (chosen / best - 1.0) if best > 0 else (0.0 if chosen == 0 else float("inf"))
    return min(r, REGRET_CAP)


def mean_capped_regret(run, sid, baseline, metric, grid_for_holdout=None):
    from horizon_variants import N_RANDOM_SUBSETS, _errors
    from backend.services import auto_discovery as ad
    grid = run.grid
    for i in grid:                      # TimesFM fallback check before deciding
        run.run(i, "timesfm")
    rng = random.Random(f"{sid}-2.3b-{run.h}")
    subsets = [tuple(sorted(rng.sample(grid, ad.DECISION_N_CUTOFFS))) for _ in range(N_RANDOM_SUBSETS)]
    eb, et = _errors(run.ev, grid, baseline, metric)
    held_grid = grid_for_holdout if grid_for_holdout is not None else grid
    regrets, rule_errors = [], 0
    for sub in subsets:
        choice, failed = decide_like_production(run.ev, list(sub), baseline, metric)
        rule_errors += failed
        r = capped_regret(eb, et, held_grid, sub, choice)
        if r is not None:
            regrets.append(r)
    run.rule_errors = getattr(run, "rule_errors", 0) + rule_errors
    return 100.0 * float(np.mean(regrets)) if regrets else None, len(regrets)


def c_side(run, values, sid):
    from holt_explosion import is_jump_cutoff
    from backend.services.reliability import explosion_index
    normal = [i for i in run.grid if not is_jump_cutoff(values[: i + 1])]
    out = {"n_normal": len(normal), "n_jump": len(run.grid) - len(normal)}
    for b in ("holt", "holt_C"):
        a, n = mean_capped_regret(run, sid, b, "mase", grid_for_holdout=normal)
        rows = [run.run(i, b) for i in normal]
        flags = [i for i, r in zip(normal, rows)
                 if r.get("pred_end") and (explosion_index(values[: i + 1], r["pred_end"], run.h) or 0) > 2.0]
        out[b] = {"regret": a, "n_regrets": n, "mase": float(np.mean([r["mase"] for r in rows])),
                  "coverage": float(np.mean([r["cov"] for r in rows])), "flags_normal": flags}
    h, c = out["holt"], out["holt_C"]
    out["ok_regret"] = c["regret"] is not None and h["regret"] is not None and c["regret"] <= h["regret"] + TIE_PP
    out["ok_mase"] = c["mase"] <= C_MASE_FACTOR * h["mase"]
    out["ok_coverage"] = abs(c["coverage"] - NOMINAL) <= abs(h["coverage"] - NOMINAL) + C_COVERAGE_PP
    out["catastrophic"] = bool((c["regret"] is not None and h["regret"] is not None
                                and c["regret"] - h["regret"] > CATASTROPHIC_PP)
                               or set(c["flags_normal"]) - set(h["flags_normal"]))
    out["passes"] = out["ok_regret"] and out["ok_mase"] and out["ok_coverage"]
    return out


# ---------------------------------------------------------------- per series

def analyze(sid, entry):
    from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
    from backend.services import auto_discovery as ad
    from backend.services.horizons import canonical_horizon
    from backend.services.seasonality import detect_seasonality, infer_frequency
    from holt_explosion import make_robust_holt
    dates = sorted(entry["values"])
    values = [entry["values"][d] for d in dates]
    pts = [TimeSeriesPoint(timestamp=d, value=v) for d, v in zip(dates, values)]
    series = TimeSeriesData(id=sid, name=sid, type="macro", unit="", points=pts, source="live")
    freq = infer_frequency(dates)
    window = ad.RECENT_WINDOW.get(freq, ad.RECENT_WINDOW_DEFAULT)
    seasonal = detect_seasonality(pts).is_seasonal
    baseline, metric = ("holt_winters", "mase_seasonal") if seasonal else ("holt", "mase")
    canon = canonical_horizon(freq)
    extra = {"holt_C": make_robust_holt("trend")}
    runs = {h: Run(sid, series, h, window, extra) for h in sorted({canon, V4_HORIZON})}
    out = {"category": entry["category"], "ya_vista": entry["ya_vista"], "title": entry["title"],
           "frequency": freq, "n": len(pts), "first": dates[0], "last": dates[-1],
           "seasonal": seasonal, "baseline": baseline, "canonical_h": canon,
           "grid_sizes": {str(h): len(r.grid) for h, r in runs.items()}}

    # capability at the canonical horizon
    cap_engines = ["holt"] + (["holt_winters"] if seasonal else []) + ["timesfm"]
    if len(runs[canon].grid) >= N_GRID:
        out["capability"] = capability(runs[canon], values, seasonal, freq, cap_engines)
    else:
        out["capability"] = {"evaluable": False, "why": f"grilla de {len(runs[canon].grid)} < {N_GRID}"}

    # v5: v4 (30) vs canonical, same rule and baseline
    evaluable = all(len(r.grid) >= N_GRID for r in runs.values())
    if evaluable and canon != V4_HORIZON:
        a4, _ = mean_capped_regret(runs[V4_HORIZON], sid, baseline, metric)
        a5, _ = mean_capped_regret(runs[canon], sid, baseline, metric)
        out["v5"] = {"evaluable": True, "A_v4": a4, "A_v5": a5, "diff": a5 - a4,
                     "improves_or_ties": a5 <= a4 + TIE_PP, "catastrophic": a5 - a4 > CATASTROPHIC_PP}
    else:
        out["v5"] = {"evaluable": False, "why": "grilla < 24 en algún horizonte" if not evaluable else "canónico = 30"}

    # variant C: only where the baseline is Holt
    if seasonal:
        out["C"] = {"evaluable": False, "why": "estacional: el motor base es Holt-Winters"}
    elif not evaluable:
        out["C"] = {"evaluable": False, "why": "grilla < 24 en algún horizonte"}
    else:
        per_h = {str(h): c_side(r, values, sid) for h, r in runs.items()}
        out["C"] = {"evaluable": True, "horizons": per_h,
                    "passes": all(v["passes"] for v in per_h.values()),
                    "catastrophic": any(v["catastrophic"] for v in per_h.values())}
    out["decide_robust_errors"] = {str(h): getattr(r, "rule_errors", 0) for h, r in runs.items()}
    return out


# ---------------------------------------------------------------- verdicts

def verdicts(res):
    cats = {}
    for sid, s in res["series"].items():
        cats.setdefault(s["category"], []).append((sid, s))
    out = {"categories": {}}
    any_cat_v5 = any_cat_c = False
    v5_ok = c_ok = True
    cat_v5_cat = any(s["v5"].get("catastrophic") for s in res["series"].values() if s["v5"].get("evaluable"))
    cat_c_cat = any(s["C"].get("catastrophic") for s in res["series"].values() if s["C"].get("evaluable"))
    for cat, items in cats.items():
        cap = [(sid, s["capability"]) for sid, s in items if s["capability"].get("engines")]
        n_cap = sum(c["has_capacity"] for _, c in cap)
        pairs = [(sid, eng, e["p"]) for sid, c in cap for eng, e in c["engines"].items()]
        holm_rej = holm([p for _, _, p in pairs])
        holm_by_series = {}
        for (sid, eng, _), rej in zip(pairs, holm_rej):
            if rej and cap and dict(cap)[sid]["engines"][eng]["skill"] > 0:
                holm_by_series.setdefault(sid, []).append(eng)
        v5s = [s["v5"] for _, s in items if s["v5"].get("evaluable")]
        cs = [s["C"] for _, s in items if s["C"].get("evaluable")]
        entry = {
            "n_series": len(items), "capability_series": n_cap,
            "has_capacity": n_cap >= 3,
            "winners": {sid: [e for e, v in c["engines"].items() if v["beats"]] for sid, c in cap},
            "holm_sensitivity": holm_by_series,
            "v5_evaluable": len(v5s), "v5_improve_or_tie": sum(v["improves_or_ties"] for v in v5s),
            "C_evaluable": len(cs), "C_passes": sum(v["passes"] for v in cs),
        }
        if len(v5s) >= 3:
            any_cat_v5 = True
            entry["v5_category_passes"] = entry["v5_improve_or_tie"] > len(v5s) / 2
            v5_ok &= entry["v5_category_passes"]
        if len(cs) >= 3:
            any_cat_c = True
            entry["C_category_passes"] = entry["C_passes"] > len(cs) / 2
            c_ok &= entry["C_category_passes"]
        out["categories"][cat] = entry
    daily = out["categories"].get("financiera_diaria", {}).get("capability_series")
    out["daily_hypothesis"] = (None if daily is None else "sostenida" if daily <= 1
                               else "refutada" if daily >= 3 else "no concluyente")
    out["v5_adopted"] = bool(any_cat_v5 and v5_ok and not cat_v5_cat)
    out["C_adopted"] = bool(any_cat_c and c_ok and not cat_c_cat)
    out["v5_any_catastrophic"], out["C_any_catastrophic"] = cat_v5_cat, cat_c_cat
    return out


def summary(res):
    v = res["verdicts"]
    print("snapshot", res["snapshot_sha256"][:16])
    for cat, e in v["categories"].items():
        print(f"\n== {cat}: capacidad en {e['capability_series']}/{e['n_series']} -> {'SÍ' if e['has_capacity'] else 'no'}"
              f" | v5 {e['v5_improve_or_tie']}/{e['v5_evaluable']} | C {e['C_passes']}/{e['C_evaluable']}")
        for sid, s in res["series"].items():
            if s["category"] != cat:
                continue
            c = s["capability"]
            if not c.get("engines"):
                print(f"   {sid:14} capacidad no evaluable: {c.get('why')}")
                continue
            eng_txt = " ".join(f"{k}:skill={x['skill']:+.3f},{x['wins']}/{x['wins']+x['losses']},p={x['p']:.3g},cob={x['coverage']:.0f}{'*' if x['beats'] else ''}"
                               for k, x in c["engines"].items())
            v5 = s["v5"]
            v5t = f"v5 A4={v5['A_v4']:.1f} A5={v5['A_v5']:.1f}" if v5.get("evaluable") else "v5 n/e"
            ct = ("C " + ("pasa" if s["C"]["passes"] else "no") + (" CATASTRÓFICO" if s["C"]["catastrophic"] else "")) if s["C"].get("evaluable") else "C n/e"
            print(f"   {sid:14}{' ★' if s['ya_vista'] else '  '} {s['frequency'][:1]} est={int(s['seasonal'])} ref={c['reference_naive'][:6]} | {eng_txt} | {v5t} | {ct}")
    print(f"\nhipótesis financieras diarias: {v['daily_hypothesis']}")
    print(f"v5 adoptada: {v['v5_adopted']} (catastrófico: {v['v5_any_catastrophic']}) | C adoptada: {v['C_adopted']} (catastrófico: {v['C_any_catastrophic']})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--selection")
    ap.add_argument("--snapshot")
    ap.add_argument("--replay")
    ap.add_argument("--out")
    ap.add_argument("--summary")
    ap.add_argument("--series", default="", help="solo estas series (prueba); el resultado oficial usa todas")
    args = ap.parse_args()
    if args.download:
        return download(args.selection, args.snapshot)
    if args.summary:
        return summary(json.loads(Path(args.summary).read_text(encoding="utf-8")))
    from backend.services.forecast_engine import TimesFMForecastEngine
    if not TimesFMForecastEngine.is_available():
        raise SystemExit("ERROR: TimesFM no carga: no se mide (pre-registro de 3.5).")
    raw = Path(args.replay).read_bytes()
    snap = json.loads(raw)
    res = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(), "selection_sha256": snap["selection_sha256"],
           "series": {}}
    wanted = [s for s in args.series.split(",") if s]
    for sid, entry in snap["series"].items():
        if wanted and sid not in wanted:
            continue
        t0 = time.perf_counter()
        try:
            res["series"][sid] = analyze(sid, entry)
        except TimesFMFellBack as e:
            raise SystemExit(f"ABORTADO: {e}. Pre-registro: si TimesFM cae a Holt, se frena y se avisa.")
        print(f"{sid}: {time.perf_counter() - t0:.0f}s", flush=True)
    res["verdicts"] = verdicts(res)
    Path(args.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("escrito", args.out)
    summary(res)


if __name__ == "__main__":
    main()
