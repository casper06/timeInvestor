"""
2.3: robust auto-discovery decision (criterion v4). Synthetic inputs only.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend.database.models import EngineDecisionModel
from backend.schemas.models import TimeSeriesPoint
from backend.services import auto_discovery as ad
from backend.services.auto_discovery import AutoDiscoveryEngine, decide_robust, recent_cutoff_indices
from tests.test_auto_discovery import _FAKE_CUTOFFS, _mock_mini_backtest, db_session  # noqa: F401


def rule(base, tfm, **kw):
    params = dict(margin=0.10, alpha=None, min_paired=7, guard=False)
    params.update(kw)
    return decide_robust("holt", base, tfm, **params)[0]


# --- decide_robust -------------------------------------------------------------

def test_too_few_pairs_keeps_baseline():
    assert rule([1.0] * 6, [0.5] * 6) == "holt"


def test_majority_and_margin_choose_timesfm():
    assert rule([1.0] * 8, [0.8] * 8) == "timesfm"


def test_majority_without_margin_is_a_tie():
    # wins on every cutoff but only by 5% (< 10% margin)
    assert rule([1.0] * 8, [0.95] * 8) == "holt"


def test_margin_without_majority_is_a_tie():
    # lower mean driven by a single cutoff; loses on 6 of 8
    base = [1.0] * 8
    tfm = [1.05] * 6 + [0.1, 0.1]
    assert np.mean(tfm) <= 0.9 * np.mean(base)
    assert rule(base, tfm) == "holt"


def test_exact_tie_goes_to_baseline():
    assert rule([1.0] * 8, [1.0] * 8) == "holt"


def test_hysteresis_keeps_timesfm_unless_baseline_clearly_wins():
    common = dict(incumbent="timesfm", hysteresis_factor=2.0)
    # baseline 15% better on every cutoff: > 10% but < 20% -> TimesFM stays
    assert rule([0.85] * 8, [1.0] * 8, **common) == "timesfm"
    # baseline 25% better on every cutoff -> switch
    assert rule([0.75] * 8, [1.0] * 8, **common) == "holt"


def test_hysteresis_keeps_baseline_unless_timesfm_clearly_wins():
    common = dict(incumbent="holt", hysteresis_factor=2.0)
    assert rule([1.0] * 8, [0.85] * 8, **common) == "holt"      # 15% < 20%
    assert rule([1.0] * 8, [0.75] * 8, **common) == "timesfm"   # 25% > 20%
    # without an incumbent the same 15% is enough
    assert rule([1.0] * 8, [0.85] * 8) == "timesfm"


def test_guard_parameter_still_blocks_when_enabled():
    kw = dict(guard=True)
    base_cov, tfm_cov = [95.0] * 8, [50.0] * 8  # 45 pp below
    assert decide_robust("holt", [1.0] * 8, [0.5] * 8, base_cov, tfm_cov, margin=0.1, alpha=None,
                         min_paired=7, **kw)[0] == "holt"
    assert ad.USE_COVERAGE_GUARD is False  # production rule doesn't use it (2.3)


def test_sign_test_mode_needs_seven_of_eight():
    # alpha=0.05 one-sided: 7/8 passes (p=0.035), 6/8 doesn't (p=0.145)
    base = [1.0] * 8
    assert decide_robust("holt", base, [0.5] * 7 + [1.5], margin=0.0, alpha=0.05, min_paired=7, guard=False)[0] == "timesfm"
    assert decide_robust("holt", base, [0.5] * 6 + [1.5] * 2, margin=0.0, alpha=0.05, min_paired=7, guard=False)[0] == "holt"


# --- recent window --------------------------------------------------------------

@pytest.mark.parametrize("n,window", [(498, 120), (1194, 504), (300, 504)])
def test_recent_cutoffs_stay_in_window_and_leave_horizon(n, window):
    idx = recent_cutoff_indices(n, 8, window)
    min_train = max(30, ad.MINI_BACKTEST_HORIZON * 2) - 1
    assert len(idx) == 8
    assert min(idx) >= max(min_train, n - window)
    assert max(idx) == n - 1 - ad.MINI_BACKTEST_HORIZON
    assert idx == sorted(idx)


def test_production_cutoffs_use_the_monthly_window(monkeypatch):
    pts = [TimeSeriesPoint(timestamp=f"{1985 + i // 12:04d}-{i % 12 + 1:02d}-01", value=100.0 + i) for i in range(498)]
    monkeypatch.setattr(AutoDiscoveryEngine, "_load_points", staticmethod(lambda sid, macro: pts))
    cutoffs = AutoDiscoveryEngine._pick_cutoffs("X", True)
    assert len(cutoffs) == ad.DECISION_N_CUTOFFS
    assert min(cutoffs) >= pts[498 - ad.RECENT_WINDOW["monthly"]].timestamp  # nothing from remote decades
    assert "1989" not in " ".join(cutoffs)


# --- hysteresis wiring in decide() -------------------------------------------------

def _capture_incumbent(monkeypatch):
    seen = {}

    def fake_run(series_id, is_macro, n_points, incumbent=None):
        seen["incumbent"] = incumbent
        return EngineDecisionModel(series_id=series_id, engine_choice="holt", evaluated_at=datetime.now(timezone.utc),
                                   mase_holt=1.0, mase_timesfm=1.0, n_points_at_evaluation=n_points,
                                   criteria_version=ad.AUTO_DISCOVERY_CRITERIA_VERSION)

    monkeypatch.setattr(AutoDiscoveryEngine, "_run_mini_backtest", staticmethod(fake_run))
    monkeypatch.setattr(ad, "_available_timesfm_engine", lambda: None)
    return seen


def test_reevaluation_passes_current_version_decision_as_incumbent(db_session, monkeypatch):  # noqa: F811
    seen = _capture_incumbent(monkeypatch)
    old = datetime.now(timezone.utc) - timedelta(days=ad.DECISION_TTL_DAYS + 1)
    db_session.add(EngineDecisionModel(series_id="INC", engine_choice="timesfm", evaluated_at=old.replace(tzinfo=None),
                                       mase_holt=1.0, mase_timesfm=0.8, n_points_at_evaluation=500,
                                       criteria_version=ad.AUTO_DISCOVERY_CRITERIA_VERSION))
    db_session.commit()
    AutoDiscoveryEngine.decide(db_session, "INC", n_points=500)
    assert seen["incumbent"] == "timesfm"


def test_older_criterion_decision_is_not_an_incumbent(db_session, monkeypatch):  # noqa: F811
    seen = _capture_incumbent(monkeypatch)
    db_session.add(EngineDecisionModel(series_id="OLD3", engine_choice="timesfm", mase_holt=1.0, mase_timesfm=0.8,
                                       n_points_at_evaluation=500, criteria_version=3))
    db_session.commit()
    AutoDiscoveryEngine.decide(db_session, "OLD3", n_points=500)
    assert seen["incumbent"] is None


# --- end to end through the mini-backtest ------------------------------------------

def test_mini_backtest_marginal_win_is_a_tie(db_session, monkeypatch):  # noqa: F811
    _mock_mini_backtest(monkeypatch, tfm_available=True, mase_holt=1.0, mase_tfm=0.95)  # 5% better
    assert AutoDiscoveryEngine.decide(db_session, "MARGINAL", n_points=500).engine_choice == "holt"


def test_mini_backtest_clear_win_is_timesfm(db_session, monkeypatch):  # noqa: F811
    _mock_mini_backtest(monkeypatch, tfm_available=True, mase_holt=1.0, mase_tfm=0.7)
    d = AutoDiscoveryEngine.decide(db_session, "CLEAR", n_points=500)
    assert d.engine_choice == "timesfm" and d.criteria_version == 4


# --- 2.3b: optional horizon for recent_cutoff_indices (not wired into v4) -----------

def test_recent_cutoffs_default_horizon_unchanged():
    assert recent_cutoff_indices(498, 8, 120) == recent_cutoff_indices(498, 8, 120, horizon=ad.MINI_BACKTEST_HORIZON)


def test_recent_cutoffs_respect_an_explicit_horizon():
    idx = recent_cutoff_indices(498, 8, 120, horizon=12)
    assert max(idx) == 498 - 1 - 12
    assert min(idx) >= 498 - 120
