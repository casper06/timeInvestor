"""
Regret of an auto-discovery decision (item 2.3c), scripts/horizon_variants.py.
Hand-made error tables with a known answer.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from horizon_variants import _grid_summary, holdout_regret, regret_table  # noqa: E402

GRID = list(range(6))


def test_zero_when_the_best_engine_on_the_held_out_cutoffs_was_chosen():
    base = {i: 1.0 for i in GRID}
    tfm = {i: 2.0 for i in GRID}
    assert holdout_regret(base, tfm, GRID, [0, 1], "holt", "holt") == 0.0


def test_relative_extra_error_of_the_wrong_choice():
    base = {i: 1.0 for i in GRID}
    tfm = {i: 1.25 for i in GRID}
    assert holdout_regret(base, tfm, GRID, [0, 1], "timesfm", "holt") == pytest.approx(0.25)


def test_scored_only_on_cutoffs_not_used_to_decide():
    # On the decision cutoffs (0, 1) TimesFM is far better; on the held-out
    # ones it's 10% worse: the regret must only see the held-out ones.
    base = {0: 5.0, 1: 5.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0}
    tfm = {0: 1.0, 1: 1.0, 2: 1.1, 3: 1.1, 4: 1.1, 5: 1.1}
    assert holdout_regret(base, tfm, GRID, [0, 1], "timesfm", "holt") == pytest.approx(0.10)


def test_unpaired_cutoffs_are_dropped_and_none_if_nothing_is_left():
    base = {0: 1.0, 1: 1.0, 2: 1.0, 3: None}
    tfm = {0: 1.0, 1: 1.0, 2: 2.0, 3: 0.1}  # cutoff 3 unpaired: ignored
    assert holdout_regret(base, tfm, [0, 1, 2, 3], [0, 1], "timesfm", "holt") == pytest.approx(1.0)
    assert holdout_regret(base, tfm, [0, 1, 2, 3], [0, 1, 2], "timesfm", "holt") is None


def test_holt_winters_baseline_is_scored_as_the_baseline():
    base = {i: 1.0 for i in GRID}
    tfm = {i: 0.8 for i in GRID}
    assert holdout_regret(base, tfm, GRID, [0], "holt_winters", "holt_winters") == pytest.approx(0.25)


def test_grid_summary_counts_wins_on_paired_cutoffs():
    s = _grid_summary({0: 1.0, 1: 2.0, 2: 1.0, 3: None}, {0: 2.0, 1: 1.0, 2: 1.0, 3: 5.0})
    assert s == {"n_paired": 3, "mean_base": pytest.approx(4 / 3), "mean_tfm": pytest.approx(4 / 3),
                 "wins_base": 1, "wins_tfm": 1, "ties": 1}


def test_regret_table_pools_series_by_category_in_percentage_points():
    res = {"series": {
        "A": {"category": "fred", "baseline": "holt", "rows": {"12": {"regrets": [0.0, 0.1]}}},
        "B": {"category": "fred", "baseline": "holt", "rows": {"12": {"regrets": [0.2, None]}}},
        "C": {"category": "fred", "baseline": "holt_winters", "rows": {"12": {"regrets": [0.0]}}},
    }}
    rows = {(c, h): (n, mean, med) for c, h, n, mean, med, _ in regret_table(res)}
    assert rows[("FRED SA", 12)] == (3, pytest.approx(10.0), pytest.approx(10.0))
    assert rows[("FRED estacional", 12)][0] == 1
