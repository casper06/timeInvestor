"""
4.17 validation (pre-registered in docs/PLAN.md 4.17, commit 24d90b4).

1. Validation series by the written rule: fred/tags/series with
   tag_names=nsa;monthly;usa, order_by=popularity desc, first page (1000);
   the first 6 that (a) are not in the POPTHM-check set, (b) have
   observation_start <= 2000-01-01 and observation_end >= 2026-01-01, (c) the
   3.0a detector marks seasonal on the 500 observations the app downloads.
2. For each (and, apart, the 10 series of the POPTHM check), a fresh v10
   decision on a COPY of the DB, and the badge with v9's rule (seasonal naive)
   and v10's (the stricter naive).
3. Adoption check: a v10 "aporta" whose engine loses the majority of cutoffs
   (wins <= losses) against the OTHER naive would block the adoption.

  DATABASE_URL=sqlite:///<copy with 'skill417' in its name> python scripts/skill_strictest_validation.py --out <json>
"""
import argparse
import json
import logging
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

CHECKED = ["POPTHM", "GFDEBTN", "GFDEGDQ188S", "IMPCH", "MTSDS133FMS", "UNRATENSA",
           "IPG2211A2N", "HOUSTNSA", "RSAFSNA", "MRTSSM4451USN"]
N_VALIDATION = 6


def pick_validation(fred_key):
    from backend.services.data_fetcher import FREDDataFetcher
    from backend.services.seasonality import detect_seasonality
    r = httpx.get("https://api.stlouisfed.org/fred/tags/series",
                  params={"tag_names": "nsa;monthly;usa", "order_by": "popularity", "sort_order": "desc",
                          "limit": 1000, "api_key": fred_key, "file_type": "json"}, timeout=30)
    r.raise_for_status()
    seen, picked = [], []
    for s in r.json()["seriess"]:
        sid = s["id"]
        if sid in CHECKED:
            seen.append((sid, "excluida: chequeo de POPTHM"))
            continue
        if not (s["observation_start"] <= "2000-01-01" and s["observation_end"] >= "2026-01-01"):
            seen.append((sid, f"excluida: historia {s['observation_start']}..{s['observation_end']}"))
            continue
        # A failed download is not one of the pre-registered criteria: retried
        # (a first run lost FEDFUNDS and CSUSHPINSA to a transient error).
        data = None
        for attempt in range(4):
            try:
                data = FREDDataFetcher().get_series(sid)
                break
            except ValueError as e:
                last_error = e
                time.sleep(10)
        if data is None:
            seen.append((sid, f"NO EVALUABLE: descarga fallida 4 veces ({last_error}); fuera de la regla"))
            continue
        seas = detect_seasonality(data.points)
        if not seas.is_seasonal:
            seen.append((sid, f"excluida: no estacional ({seas.reason[:80]})"))
            continue
        seen.append((sid, "elegida"))
        picked.append(sid)
        if len(picked) == N_VALIDATION:
            break
    return picked, seen


def evaluate(db, sid):
    from backend.services.auto_discovery import AutoDiscoveryEngine
    from backend.services.data_fetcher import FREDDataFetcher
    from backend.services.forecast_skill import skill_for_decision, skill_from_pairs
    data = FREDDataFetcher().get_series(sid)
    d = AutoDiscoveryEngine.decide(db, sid, len(data.points), is_macro=True)
    ev = json.loads(d.cutoff_errors_json)
    key = "tfm" if d.engine_choice == "timesfm" else "base"
    rows = ev["cutoffs"]
    v10 = skill_for_decision(d)
    out = {"series": sid, "decision": f"v{d.criteria_version} {d.engine_choice} h={d.horizon}",
           "seasonal": ev["naive"] == "naive_estacional", "v10": v10.model_dump()}
    if ev["naive"] == "naive_estacional":
        v9 = skill_from_pairs([r.get(key) for r in rows], [r.get("snaive") for r in rows], "naive_estacional", "v9")
        triples = [(r[key], r["rw"], r["snaive"]) for r in rows
                   if r.get(key) is not None and r.get("rw") is not None and r.get("snaive") is not None]
        other_idx = 1 if v10.naive == "naive_estacional" else 2
        w = sum(t[0] < t[other_idx] for t in triples)
        l = sum(t[0] > t[other_idx] for t in triples)
        out.update(v9=v9.model_dump(), sum_rw=sum(t[1] for t in triples), sum_snaive=sum(t[2] for t in triples),
                   other_naive_wins=w, other_naive_losses=l,
                   blocks_adoption=(v10.state == "aporta" and w <= l))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    assert "skill417" in os.environ.get("DATABASE_URL", ""), "DATABASE_URL tiene que ser una COPIA ('skill417')"
    logging.disable(logging.CRITICAL)
    from backend.config import settings
    from backend.database.connection import SessionLocal, init_db
    init_db()
    db = SessionLocal()
    picked, seen = pick_validation(settings.FRED_API_KEY)
    print("validación:", picked, flush=True)
    result = {"rule": "docs/PLAN.md 4.17 (24d90b4)", "selection_trace": seen, "validation": [], "checked": []}
    for sid in picked:
        result["validation"].append(evaluate(db, sid))
        print("  ", json.dumps({k: result["validation"][-1].get(k) for k in ("series", "decision", "seasonal")}), flush=True)
    for sid in CHECKED:
        try:
            result["checked"].append(evaluate(db, sid))
        except Exception as e:
            result["checked"].append({"series": sid, "error": str(e)})
    json.dump(result, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("escrito:", a.out)


if __name__ == "__main__":
    main()
