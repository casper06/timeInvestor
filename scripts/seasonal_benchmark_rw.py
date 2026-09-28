"""
4.17: the random walk on the 3.0d cutoffs, so the seasonal catalog's badge can
compare against the stricter of the two naives. Same snapshot, cutoffs, horizon
(12) and scale as scripts/seasonal_benchmark.py (MASE scaled by the in-sample
seasonal naive, mean |y_t - y_{t-12}|). Writes one number per series and cutoff.

  python scripts/seasonal_benchmark_rw.py \\
      --snapshot data/snapshots/seasonal_benchmark_2026-09-26.json \\
      --results docs/results/seasonal_benchmark_2026-09-26.json \\
      --out docs/results/seasonal_benchmark_rw_2026-09-28.json
"""
import argparse
import hashlib
import json

import numpy as np

M, H = 12, 12


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    raw = open(a.snapshot, "rb").read()
    snap = json.loads(raw)
    res = json.load(open(a.results, encoding="utf-8"))
    assert res["snapshot_sha256"] == hashlib.sha256(raw).hexdigest(), "no es el snapshot de 3.0d"
    out = {"snapshot_sha256": res["snapshot_sha256"], "horizon": H,
           "metric": "MASE estacional del random walk (último valor repetido), misma escala que 3.0d",
           "series": {}}
    for sid, s in res["series"].items():
        vm = snap["series"][sid]["values"]
        dates = sorted(vm)
        vals = [vm[d] for d in dates]
        per = {}
        for cd in s["cutoffs"]:
            i = dates.index(cd)
            train = np.array(vals[: i + 1], float)
            actual = np.array(vals[i + 1: i + 1 + H], float)
            scale = float(np.mean(np.abs(train[M:] - train[:-M])))
            per[cd] = float(np.mean(np.abs(actual - train[-1])) / scale)
        out["series"][sid] = per
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
    print(f"escrito: {a.out} ({len(out['series'])} series)")


if __name__ == "__main__":
    main()
