"""
Helpers of scripts/fred_category_benchmark.py (item 3.5): the sign test, Holm,
the capped regret and the pre-registered verdict logic. Hand-made inputs with
a known answer.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fred_category_benchmark import capped_regret, holm, sign_test_p, verdicts  # noqa: E402
from horizon_variants import holdout_regret  # noqa: E402


def test_sign_test_one_sided():
    assert sign_test_p(18, 6) == pytest.approx(0.0113, abs=1e-3)   # passes Bonferroni with k = 3
    assert sign_test_p(17, 7) == pytest.approx(0.0320, abs=1e-3)   # doesn't: 0.032 > 0.05 / 3
    assert sign_test_p(0, 0) == 1.0                                  # all ties: no evidence


def test_holm_step_down():
    assert holm([0.001, 0.02, 0.04]) == [True, True, True]        # 0.001<0.0167, 0.02<0.025, 0.04<0.05
    assert holm([0.001, 0.03, 0.04]) == [True, False, False]      # 0.03 > 0.025 stops the procedure


def test_capped_regret_matches_holdout_regret_when_best_error_is_positive():
    base = {0: 1.0, 1: 2.0, 2: 1.5, 3: 1.2}
    tfm = {0: 1.1, 1: 1.0, 2: 1.4, 3: 1.3}
    for sub, choice in [((0,), "holt"), ((1,), "timesfm"), ((2, 3), "holt")]:
        r = holdout_regret(base, tfm, list(base), sub, choice, "holt")
        assert capped_regret(base, tfm, list(base), sub, choice) == pytest.approx(min(r, 1.0))


def test_capped_regret_zero_best_error_is_the_cap_not_zero():
    base = {0: 0.0, 1: 0.0, 2: 0.0}
    tfm = {0: 0.5, 1: 0.5, 2: 0.5}
    assert capped_regret(base, tfm, [0, 1, 2], (0,), "timesfm") == 1.0   # chose the worse: capped
    assert capped_regret(base, tfm, [0, 1, 2], (0,), "holt") == 0.0      # chose the exact one
    assert holdout_regret(base, tfm, [0, 1, 2], (0,), "timesfm", "holt") == 0.0  # the old edge case


def _series(cat, cap=False, v5=None, c=None):
    return {"category": cat,
            "capability": {"engines": {"timesfm": {"beats": cap, "p": 0.001 if cap else 0.5, "skill": 0.2 if cap else -0.1}},
                           "has_capacity": cap},
            "v5": v5 or {"evaluable": False},
            "C": c or {"evaluable": False}}


def _v5(diff):
    return {"evaluable": True, "improves_or_ties": diff <= 2.0, "catastrophic": diff > 25.0}


def test_verdicts_follow_the_pre_registered_rules():
    res = {"series": {
        # daily: 1 of 5 with capacity -> hypothesis holds; v5 3 of 5 ok -> category passes
        **{f"D{i}": _series("financiera_diaria", cap=(i == 0), v5=_v5(-1 if i < 3 else 5)) for i in range(5)},
        # monthly: 3 of 5 with capacity -> category has capacity; v5 2 of 5 -> fails
        **{f"M{i}": _series("mensual_sa_real", cap=(i < 3), v5=_v5(-1 if i < 2 else 5)) for i in range(5)},
    }}
    v = verdicts(res)
    assert v["daily_hypothesis"] == "sostenida"
    assert v["categories"]["mensual_sa_real"]["has_capacity"] is True
    assert v["categories"]["financiera_diaria"]["v5_category_passes"] is True
    assert v["categories"]["mensual_sa_real"]["v5_category_passes"] is False
    assert v["v5_adopted"] is False  # every category with >= 3 evaluable series must pass


def test_one_catastrophic_series_blocks_adoption():
    res = {"series": {f"D{i}": _series("financiera_diaria", v5=_v5(30 if i == 0 else -1)) for i in range(5)}}
    v = verdicts(res)
    assert v["categories"]["financiera_diaria"]["v5_category_passes"] is True
    assert v["v5_adopted"] is False


def test_no_category_with_three_evaluable_series_means_not_adopted():
    res = {"series": {f"Q{i}": _series("trimestral", v5=_v5(-5) if i < 2 else None) for i in range(5)}}
    assert verdicts(res)["v5_adopted"] is False


def test_daily_hypothesis_thresholds():
    for n_cap, expected in [(0, "sostenida"), (1, "sostenida"), (2, "no concluyente"), (3, "refutada")]:
        res = {"series": {f"D{i}": _series("financiera_diaria", cap=(i < n_cap)) for i in range(5)}}
        assert verdicts(res)["daily_hypothesis"] == expected
