"""
Series selection for 3.5 (docs/PLAN.md), by the rule pre-registered there.
Uses ONLY FRED metadata (tags/series, series/categories, category,
series/release): no observations are downloaded here.

    python scripts/fred_category_select.py --out docs/results/fred_category_selection_2026-09-27.json

Rule, per category: walk FRED's list for the category's tags (frequency tag +
usa + nation, excluding "discontinued"), ordered by FRED popularity
(descending, at query time), and keep a series if it passes every filter,
until 5 are kept:
- active: last observation on or after ACTIVE_SINCE[freq];
- history: first observation on or before HISTORY_BEFORE[freq];
- not a binary indicator (FRED units "+1 or 0", e.g. USREC): MASE and
  skill don't apply to a 0/1 variable (amendment 1, before any data);
- topic (TOPIC below), judged with FRED's own category tree;
- at most one series per FRED release within the category.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "https://api.stlouisfed.org/fred"
N_PER_CATEGORY = 5

# FRED root categories (fred/category/children?category_id=0, 2026-09-27).
ROOT_MONEY, ROOT_LABOR, ROOT_NIPA, ROOT_PRODUCTION, ROOT_PRICES = 32991, 10, 32992, 1, 32455
REAL_ROOTS = {ROOT_PRODUCTION, ROOT_LABOR, ROOT_NIPA}
NATIONAL_TOPIC_ROOTS = {ROOT_MONEY, ROOT_LABOR, ROOT_NIPA, ROOT_PRODUCTION, ROOT_PRICES}

CATEGORIES = {
    "mensual_nsa_real": {"tags": "monthly;nsa;usa;nation", "freq": "monthly", "topic": "real"},
    "mensual_sa_real": {"tags": "monthly;sa;usa;nation", "freq": "monthly", "topic": "real"},
    "trimestral": {"tags": "quarterly;usa;nation", "freq": "quarterly", "topic": "national"},
    "semanal": {"tags": "weekly;usa;nation", "freq": "weekly", "topic": "national"},
    "financiera_diaria": {"tags": "daily;usa;nation", "freq": "daily", "topic": "financial"},
}
ACTIVE_SINCE = {"daily": "2026-09-01", "weekly": "2026-09-01", "monthly": "2026-06-01", "quarterly": "2026-01-01"}
# Enough history for the 24-cutoff grid inside the v4 window at the canonical
# horizon (monthly 20 years, quarterly 40 years, weekly 10 years, daily 2 years).
HISTORY_BEFORE = {"daily": "2024-09-01", "weekly": "2016-09-01", "monthly": "2006-09-01", "quarterly": "1986-09-01"}
FINANCIAL_TAGS = {"interest rate", "spread", "volatility"}
ALREADY_SEEN = {"HOUSTNSA", "INDPRO", "IPG2211A2N", "UNRATE", "RSAFSNA"}  # FRED series of the 2.5 snapshot


class Fred:
    def __init__(self, key):
        self.key, self._cat = key, {}

    def get(self, endpoint, **params):
        for attempt in range(4):
            r = httpx.get(f"{BASE}/{endpoint}", params={**params, "api_key": self.key, "file_type": "json"}, timeout=30)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            time.sleep(0.6)  # FRED: 120 requests/minute
            return r.json()
        r.raise_for_status()

    def root_of(self, category_id):
        """Root ancestor of a FRED category (cached)."""
        chain, cid = [], category_id
        while cid not in self._cat:
            cat = self.get("category", category_id=cid)["categories"][0]
            chain.append(cid)
            if cat["parent_id"] == 0:
                self._cat[cid] = cid
                break
            cid = cat["parent_id"]
        root = self._cat[cid]
        for c in chain:
            self._cat[c] = root
        return root


def topic_ok(fred, sid, topic):
    roots = {fred.root_of(c["id"]) for c in fred.get("series/categories", series_id=sid)["categories"]}
    if topic == "real":
        return bool(roots & REAL_ROOTS) and not (roots & {ROOT_PRICES, ROOT_MONEY}), sorted(roots)
    if topic == "national":
        return bool(roots & NATIONAL_TOPIC_ROOTS), sorted(roots)
    tags = {t["name"] for t in fred.get("series/tags", series_id=sid)["tags"]}
    return (ROOT_MONEY in roots) and bool(tags & FINANCIAL_TAGS), sorted(roots)


def select(fred, name, spec):
    kept, releases, rejected, offset = [], set(), [], 0
    while len(kept) < N_PER_CATEGORY:
        page = fred.get("tags/series", tag_names=spec["tags"], exclude_tag_names="discontinued",
                        order_by="popularity", sort_order="desc", limit=100, offset=offset)["seriess"]
        if not page:
            break
        for s in page:
            if len(kept) >= N_PER_CATEGORY:
                break
            sid, why = s["id"], None
            if s["observation_end"] < ACTIVE_SINCE[spec["freq"]]:
                why = f"inactiva (última obs. {s['observation_end']})"
            elif s["observation_start"] > HISTORY_BEFORE[spec["freq"]]:
                why = f"historia corta (desde {s['observation_start']})"
            elif s.get("units") == "+1 or 0" or s.get("units_short") == "+1 or 0":
                why = "indicador binario (unidades +1 or 0): enmienda 1"
            else:
                ok, roots = topic_ok(fred, sid, spec["topic"])
                if not ok:
                    why = f"tema fuera de la categoría (raíces {roots})"
                else:
                    rel = fred.get("series/release", series_id=sid)["releases"][0]["name"]
                    if rel in releases:
                        why = f"release ya representado ({rel})"
                    else:
                        releases.add(rel)
                        kept.append({"id": sid, "title": s["title"], "frequency": s["frequency_short"],
                                     "seasonal_adjustment": s["seasonal_adjustment_short"],
                                     "units": s["units_short"], "popularity": s["popularity"],
                                     "observation_start": s["observation_start"],
                                     "observation_end": s["observation_end"], "release": rel,
                                     "roots": roots, "ya_vista": sid in ALREADY_SEEN})
            if why:
                rejected.append({"id": sid, "popularity": s["popularity"], "why": why})
        offset += 100
    return {"spec": spec, "series": kept, "rejected_before_filling": rejected}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    from backend.config import settings
    fred = Fred(settings.FRED_API_KEY)
    res = {"queried_at": time.strftime("%Y-%m-%d %H:%M"), "rule": "ver docstring y docs/PLAN.md 3.5",
           "active_since": ACTIVE_SINCE, "history_before": HISTORY_BEFORE, "categories": {}}
    for name, spec in CATEGORIES.items():
        res["categories"][name] = select(fred, name, spec)
        print(name, [s["id"] for s in res["categories"][name]["series"]], flush=True)
    Path(args.out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print("escrito", args.out)


if __name__ == "__main__":
    main()
