"""
3.4: forecast capability with the data as it was known at each cutoff
(ALFRED vintages) against the revised data of today. Pre-registered in
docs/PLAN.md 3.4 (commit 477b979) before downloading anything. Measures only:
changes no criterion or catalog.

  python scripts/vintage_benchmark.py --fetch  --snapshot data/snapshots/vintages_<date>.json
  python scripts/vintage_benchmark.py --replay data/snapshots/vintages_<date>.json --out docs/results/vintage_benchmark_<date>.json

Per series and cutoff c:
  - training "de época": the series as published on c (vintage_dates=c), last observation t;
  - training "revisada": today's series cut at the same t (same period, only revisions differ);
  - truth for the 12 months after t: first release (output_type=4) and today's revised value.
Capability as in 3.5 (capability() in scripts/fred_category_benchmark.py): engines
holt, holt_winters (if seasonal by 3.0a on the full revised series) and timesfm
(real; a fallback stops the run); reference = the stricter naive (lower total
error) computed from the same training data; an engine beats it if the sign test
gives p < 0.05/k and skill > 0; the series has capability if any engine does.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date

import httpx
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

SERIES = ["IPG2211A2N", "HOUSTNSA", "RSAFSNA", "MRTSSM4451USN", "HOUST", "INDPRO", "JTSJOL", "PSAVERT", "UNRATE"]
FIRST_VINTAGE_MAX = "2016-12-31"
N_CUTOFFS = 24
H = 12
M = 12
API = "https://api.stlouisfed.org/fred"
WIDE = {"realtime_start": "1776-07-04", "realtime_end": "9999-12-31"}
PAUSE = 0.6        # FRED: 120 requests/minute


def _get(path, key, **params):
    params.update(api_key=key, file_type="json")
    for attempt in range(3):
        r = httpx.get(f"{API}/{path}", params=params, timeout=60)
        time.sleep(PAUSE)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(30)
            continue
        raise RuntimeError(f"{path} {params.get('series_id')} HTTP {r.status_code}: {r.text[:200]}")
    raise RuntimeError(f"{path}: 429 tres veces")


def _obs(payload):
    return {o["date"]: float(o["value"]) for o in payload["observations"] if o["value"] not in (".", "")}


def _add_months(d, k):
    y, m = int(d[:4]), int(d[5:7]) + k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-01"


def fetch(snapshot_path):
    from backend.config import settings
    key = settings.FRED_API_KEY
    snap = {"created_at": date.today().isoformat(), "rule": "docs/PLAN.md 3.4 (477b979)", "series": {}, "excluded": {}}
    for sid in SERIES:
        vd = _get("series/vintagedates", key, series_id=sid, **WIDE)["vintage_dates"]
        first = vd[0] if vd else None
        if first is None or first > FIRST_VINTAGE_MAX:
            snap["excluded"][sid] = f"primera fecha de vintage {first} > {FIRST_VINTAGE_MAX}"
            print(f"{sid}: excluida ({snap['excluded'][sid]})", flush=True)
            continue
        current = _obs(_get("series/observations", key, series_id=sid, limit=100000))
        first_release = _obs(_get("series/observations", key, series_id=sid, output_type=4, limit=100000, **WIDE))
        last = max(current)
        start = _add_months(first[:7] + "-01", 1)
        stop = _add_months(last, -H)
        months = []
        d = start
        while d <= stop:
            months.append(d)
            d = _add_months(d, 1)
        idx = np.linspace(0, len(months) - 1, N_CUTOFFS).round().astype(int)
        cutoffs = [months[i][:8] + "15" for i in sorted(set(idx))]
        vintages = {}
        for c in cutoffs:
            vintages[c] = _obs(_get("series/observations", key, series_id=sid, vintage_dates=c, limit=100000))
        snap["series"][sid] = {"first_vintage": first, "n_vintage_dates": len(vd), "current": current,
                               "first_release": first_release, "cutoffs": cutoffs, "vintages": vintages}
        print(f"{sid}: vintages desde {first}, {len(cutoffs)} cutoffs {cutoffs[0]}..{cutoffs[-1]}", flush=True)
    raw = json.dumps(snap, sort_keys=True).encode()
    os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
    open(snapshot_path, "wb").write(raw)
    print(f"snapshot {snapshot_path} sha256 {hashlib.sha256(raw).hexdigest()}")


def _points(d):
    from backend.schemas.models import TimeSeriesPoint
    return [TimeSeriesPoint(timestamp=k, value=v) for k, v in sorted(d.items())]


def _forecast(engine_name, points):
    from backend.services.forecast_engine import (
        DampedHoltForecastEngine, HoltWintersForecastEngine, NotSeasonalError, TimesFMForecastEngine)
    eng = {"holt": DampedHoltForecastEngine, "holt_winters": HoltWintersForecastEngine,
           "timesfm": TimesFMForecastEngine}[engine_name]()
    try:
        res = eng.forecast(points, horizon=H, confidence=0.8, freq="M")
    except NotSeasonalError:
        return None
    if engine_name == "timesfm" and res.is_fallback:
        raise SystemExit(f"TimesFM cayó a Holt ({res.fallback_reason}); no se cuenta como TimesFM. Se frena.")
    return np.array(res.values[:H], float)


def capability(rows, engines, seasonal):
    """rows: per cutoff {engine: forecast, 'rw': ..., 'sn': ..., 'truth': ...}; 3.5's rule."""
    from fred_category_benchmark import ALPHA, sign_test_p
    usable = [r for r in rows if all(r.get(e) is not None for e in engines)]
    rw = [float(np.mean(np.abs(r["truth"] - r["rw"]))) for r in usable]
    sn = [float(np.mean(np.abs(r["truth"] - r["sn"]))) for r in usable] if seasonal else []
    ref_name, ref = "random_walk", rw
    if seasonal and sum(sn) < sum(rw):
        ref_name, ref = "naive_estacional", sn
    k = len(engines)
    out = {"reference_naive": ref_name, "k": k, "n_cutoffs": len(usable), "engines": {}}
    for e in engines:
        mae = [float(np.mean(np.abs(r["truth"] - r[e]))) for r in usable]
        wins = sum(a < b for a, b in zip(mae, ref))
        losses = sum(a > b for a, b in zip(mae, ref))
        p = sign_test_p(wins, losses)
        skill = 1.0 - sum(mae) / sum(ref) if sum(ref) > 0 else None
        out["engines"][e] = {"wins": wins, "losses": losses, "p": p, "skill": skill,
                             "beats": bool(p < ALPHA / k and skill is not None and skill > 0)}
    out["has_capacity"] = any(v["beats"] for v in out["engines"].values())
    return out


def replay(snapshot_path, out_path):
    from backend.services.seasonality import detect_seasonality, seasonal_naive_forecast
    raw = open(snapshot_path, "rb").read()
    snap = json.loads(raw)
    result = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(), "rule": snap["rule"], "excluded": snap["excluded"],
              "series": {}}
    for sid, s in snap["series"].items():
        seasonal = detect_seasonality(_points(s["current"])).is_seasonal
        engines = ["holt"] + (["holt_winters"] if seasonal else []) + ["timesfm"]
        rows = {("epoca", "primera"): [], ("epoca", "revisada"): [], ("revisada", "primera"): [],
                ("revisada", "revisada"): []}
        revisions = []
        for c in s["cutoffs"]:
            vint = s["vintages"][c]
            t = max(vint)
            future = [_add_months(t, k) for k in range(1, H + 1)]
            if not all(f in s["current"] and f in s["first_release"] for f in future):
                continue
            train = {"epoca": {k: v for k, v in vint.items() if k <= t},
                     "revisada": {k: v for k, v in s["current"].items() if k <= t}}
            truth = {"primera": np.array([s["first_release"][f] for f in future]),
                     "revisada": np.array([s["current"][f] for f in future])}
            common = [k for k in train["epoca"] if k in train["revisada"]][-60:]
            revisions.append(float(np.mean([abs(train["revisada"][k] / train["epoca"][k] - 1) for k in common
                                            if train["epoca"][k] != 0])) * 100)
            fc = {}
            for dv, tr in train.items():
                vals = np.array([v for _, v in sorted(tr.items())], float)
                f = {e: _forecast(e, _points(tr)) for e in engines}
                f["rw"] = np.repeat(vals[-1], H)
                f["sn"] = seasonal_naive_forecast(vals, H, M) if seasonal else None
                fc[dv] = f
            for (dv, tv) in rows:
                rows[(dv, tv)].append({**fc[dv], "truth": truth[tv]})
        caps = {f"{dv}|{tv}": capability(r, engines, seasonal) for (dv, tv), r in rows.items()}
        rev, rt = caps["revisada|revisada"]["has_capacity"], caps["epoca|primera"]["has_capacity"]
        result["series"][sid] = {
            "first_vintage": s["first_vintage"], "seasonal": seasonal, "engines": engines,
            "n_cutoffs_usable": len(rows[("epoca", "primera")]),
            "mean_abs_revision_last60_pct": float(np.mean(revisions)) if revisions else None,
            "capability": caps,
            "verdict": ("no se sostiene" if rev and not rt else
                        "aparece en tiempo real" if rt and not rev else
                        "se sostiene" if rev and rt else "sin capacidad en ninguna"),
        }
        print(f"{sid}: revisada|revisada={rev} epoca|primera={rt} -> {result['series'][sid]['verdict']}", flush=True)
    json.dump(result, open(out_path, "w", encoding="utf-8"), indent=1)
    print("escrito:", out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--snapshot")
    ap.add_argument("--replay")
    ap.add_argument("--out")
    a = ap.parse_args()
    import logging
    logging.disable(logging.CRITICAL)
    if a.fetch:
        fetch(a.snapshot)
    else:
        replay(a.replay, a.out)


if __name__ == "__main__":
    main()
