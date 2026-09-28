"""
4.17 (criterion v10, pre-registered in docs/PLAN.md 4.17, commit 24d90b4): on
a seasonal series the skill badge compares against the STRICTER naive, the one
with the lower total error on the decision's cutoffs (3.5's capability()).
Fixtures: the per-cutoff MAEs measured on 2026-09-27 on a DB copy (naive check,
bitácora), GFDEGDQ188S and MTSDS133FMS, TimesFM at 4 and 12 steps.
"""
import json

import numpy as np
import pytest

from backend.database.models import EngineDecisionModel
from backend.services.forecast_skill import (
    CATALOG_RW_EVIDENCE, CATALOG_SKILL_EVIDENCE, skill_for_catalog, skill_for_decision, stricter_naive,
)

# (TimesFM, random walk, seasonal naive) MAE per cutoff, as measured.
GFDEGDQ188S = [
    (1.4130203326416009, 0.8067199999999985, 2.379525000000001),
    (0.5060248480224594, 0.5734049999999975, 1.1803949999999972),
    (1.0650176013183597, 1.000802499999999, 0.6391050000000043),
    (19.355691372680663, 19.848917499999995, 21.596645),
    (0.7755533416748079, 2.6608400000000003, 4.774744999999999),
    (1.7802165826416037, 0.6573999999999991, 2.065809999999999),
    (0.45275579895019646, 0.8355849999999982, 2.699849999999998),
    (1.0475145574951163, 1.5796899999999958, 1.18975),
]
MTSDS133FMS = [
    (43372.31172214542, 116540.31747469417, 46197.25455396833),
    (57439.031129233765, 126528.79648564919, 44007.980490256676),
    (99917.31820710667, 321554.5008136549, 102260.29390264749),
    (95191.41423739, 175732.79978721833, 250458.0422692075),
    (124943.04070187919, 135306.4615077375, 190107.65658723167),
    (109397.40677643752, 168427.9545086575, 116793.98324095499),
    (106522.74501596416, 190039.47927316165, 120749.30186087335),
    (85980.12877464415, 212071.37314440662, 81947.97457697583),
]


def _decision(rows, naive="naive_estacional", engine="timesfm", with_both=True, horizon=4):
    cut = []
    for i, (m, rw, sn) in enumerate(rows):
        r = {"cutoff": f"2020-{i + 1:02d}-01", "base": m * 1.5, "tfm": m,
             "naive": sn if naive == "naive_estacional" else rw}
        if with_both:
            r.update(rw=rw, snaive=sn)
        cut.append(r)
    return EngineDecisionModel(series_id="X", engine_choice=engine, horizon=horizon, criteria_version=10,
                               cutoff_errors_json=json.dumps({"naive": naive, "cutoffs": cut}))


def test_gfdegdq188s_goes_from_aporta_to_no_aporta():
    """v9 compared it with the seasonal naive (7-1, −28%: aporta); the random
    walk has the lower total error, and against it it's 5-3, −5.6%: no aporta."""
    old = _decision(GFDEGDQ188S, with_both=False)          # a v9 row: only the seasonal naive
    assert skill_for_decision(old).state == "no_evaluado"   # re-evaluated under v10, not guessed
    s = skill_for_decision(_decision(GFDEGDQ188S))
    assert s.naive == "random_walk" and s.state == "no_aporta"
    assert (s.wins, s.losses, s.n_pairs) == (5, 3, 8)
    assert s.rel_gap == pytest.approx(-0.056, abs=1e-3)
    assert "el naive más exigente de los dos, por error total" in s.source


def test_when_the_seasonal_naive_is_stricter_it_is_the_reference():
    s = skill_for_decision(_decision(MTSDS133FMS, horizon=12))
    assert s.naive == "naive_estacional" and s.state == "aporta" and (s.wins, s.losses) == (6, 2)


def test_tie_goes_to_the_random_walk():
    assert stricter_naive(10.0, 10.0) == "random_walk"
    assert stricter_naive(10.0, 9.99) == "naive_estacional"


def test_non_seasonal_series_is_unchanged():
    rows = [(0.8, 1.0, None)] * 8
    s = skill_for_decision(_decision(rows, naive="random_walk"))
    assert s.naive == "random_walk" and s.state == "aporta"


def test_catalog_rw_evidence_matches_the_versioned_files():
    r = json.load(open("docs/results/seasonal_benchmark_2026-09-26.json", encoding="utf-8"))
    rw = json.load(open("docs/results/seasonal_benchmark_rw_2026-09-28.json", encoding="utf-8"))
    assert rw["snapshot_sha256"] == r["snapshot_sha256"]
    for sid, (eng, *_) in CATALOG_SKILL_EVIDENCE.items():
        m = {c["cutoff"]: c["mase_s"] for c in r["series"][sid]["per_cutoff"][eng]}
        pairs = [(m[k], rw["series"][sid][k]) for k in m if m[k] is not None and k in rw["series"][sid]]
        wins, losses, n, mm, mr = CATALOG_RW_EVIDENCE[sid]
        assert (sum(a < b for a, b in pairs), sum(a > b for a, b in pairs), len(pairs)) == (wins, losses, n)
        assert np.mean([a for a, _ in pairs]) == pytest.approx(mm, abs=1e-6)
        assert np.mean([b for _, b in pairs]) == pytest.approx(mr, abs=1e-6)


@pytest.mark.parametrize("sid", list(CATALOG_SKILL_EVIDENCE))
def test_catalog_keeps_the_seasonal_naive_as_the_stricter_one(sid):
    """In the 4 catalog series the seasonal naive has the lower total error,
    so the verdict stays; the reason now says why that naive."""
    s = skill_for_catalog(sid, CATALOG_SKILL_EVIDENCE[sid][0])
    assert s.naive == "naive_estacional" and s.state == "aporta"
    assert "el naive más exigente de los dos" in s.source
