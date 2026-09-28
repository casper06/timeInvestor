"""
Forecast skill per series (4.13), criterion pre-registered in docs/PLAN.md.
Hand-made errors and fake backtests with a known answer.
"""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.database.models import EngineDecisionModel
from backend.schemas.models import TimeSeriesPoint
from backend.services import auto_discovery as ad
from backend.services.auto_discovery import AutoDiscoveryEngine
from backend.services.backtest_engine import BacktestEngine
from backend.services.engine_selector import EngineSelector
from backend.services.forecast_skill import CATALOG_SKILL_EVIDENCE, skill_for_decision, skill_from_pairs
from tests.test_auto_discovery import _FAKE_CUTOFFS, _FAKE_TIMESFM, _mock_mini_backtest, db_session  # noqa: F401


# ---- the rule ----

def test_majority_and_margin_is_aporta():
    s = skill_from_pairs([0.8] * 6 + [1.2] * 2, [1.0] * 8, "random_walk", "t")
    assert s.state == "aporta" and (s.wins, s.losses, s.n_pairs) == (6, 2, 8)
    assert s.rel_gap == pytest.approx(0.9 / 1.0 - 1)
    assert "random walk" in s.reason and "6 de 8" in s.reason


def test_majority_without_the_margin_is_no_aporta():
    s = skill_from_pairs([0.97] * 6 + [1.02] * 2, [1.0] * 8, "random_walk", "t")   # 2.5% better
    assert s.state == "no_aporta"


def test_margin_without_majority_is_no_aporta():
    s = skill_from_pairs([0.2] * 3 + [1.1] * 5, [1.0] * 8, "naive_estacional", "t")  # mean 36% lower, 3 of 8
    assert s.state == "no_aporta" and "naive estacional" in s.reason


def test_fewer_than_seven_pairs_is_not_evaluated():
    s = skill_from_pairs([0.5] * 6 + [None, None], [1.0] * 8, "random_walk", "t")
    assert s.state == "no_evaluado" and "solo 6 cutoffs" in s.reason


# ---- the catalog evidence is the versioned 3.0d result ----

def test_catalog_evidence_matches_the_versioned_3_0d_json():
    r = json.load(open("docs/results/seasonal_benchmark_2026-09-26.json", encoding="utf-8"))
    for sid, (eng, wins, losses, n, mm, mn) in CATALOG_SKILL_EVIDENCE.items():
        pc = r["series"][sid]["per_cutoff"]
        m = {c["cutoff"]: c["mase_s"] for c in pc[eng]}
        nv = {c["cutoff"]: c["mase_s"] for c in pc["seasonal_naive"]}
        pairs = [(m[k], nv[k]) for k in m if m.get(k) is not None and nv.get(k) is not None]
        assert (sum(a < b for a, b in pairs), sum(a > b for a, b in pairs), len(pairs)) == (wins, losses, n)
        assert np.mean([a for a, _ in pairs]) == pytest.approx(mm, abs=1e-6)
        assert np.mean([b for _, b in pairs]) == pytest.approx(mn, abs=1e-6)


# ---- the decision stores the evidence; the selector reports the state ----

def _fake_with_naive(monkeypatch, tfm_mae=0.5, base_mae=1.0, naive_mae=0.9):
    def fake(*, engine_override, cutoff_date, **kw):
        tfm = engine_override is _FAKE_TIMESFM
        mae = tfm_mae if tfm else base_mae
        return SimpleNamespace(
            metrics=SimpleNamespace(mase=mae, mase_seasonal=mae, mae=mae, undefined={}),
            naive_metrics=SimpleNamespace(mae=naive_mae), seasonal_naive_metrics=None,
            interval_coverage=80.0, is_fallback=False, model_name="x", interval_level=0.80)
    monkeypatch.setattr(BacktestEngine, "run_backtest", staticmethod(fake))


def test_decision_stores_per_cutoff_errors_and_the_chosen_engine_is_scored(db_session, monkeypatch):  # noqa: F811
    _mock_mini_backtest(monkeypatch, tfm_available=True)
    _fake_with_naive(monkeypatch, tfm_mae=0.5, base_mae=1.0, naive_mae=0.9)
    d = AutoDiscoveryEngine.decide(db_session, "SKILLED", n_points=500)
    data = json.loads(d.cutoff_errors_json)
    assert data["naive"] == "random_walk" and len(data["cutoffs"]) == len(_FAKE_CUTOFFS)
    # v10 (4.17): both naives per cutoff; the fake backtest has no seasonal naive.
    assert data["cutoffs"][0] == {"cutoff": _FAKE_CUTOFFS[0], "base": 1.0, "tfm": 0.5, "naive": 0.9,
                                  "rw": 0.9, "snaive": None}
    assert d.engine_choice == "timesfm"
    s = skill_for_decision(d)
    assert s.state == "aporta" and s.wins == len(_FAKE_CUTOFFS)


def test_holt_chosen_and_worse_than_the_naive_is_no_aporta(db_session, monkeypatch):  # noqa: F811
    _mock_mini_backtest(monkeypatch, tfm_available=True)
    _fake_with_naive(monkeypatch, tfm_mae=1.5, base_mae=1.0, naive_mae=0.95)   # Holt chosen, naive better
    d = AutoDiscoveryEngine.decide(db_session, "NOSKILL", n_points=500)
    assert d.engine_choice == "holt" and skill_for_decision(d).state == "no_aporta"


def test_old_decision_without_evidence_is_not_evaluated_with_reason():
    d = EngineDecisionModel(series_id="OLD", engine_choice="holt", mase_holt=1.0, n_points_at_evaluation=300)
    s = skill_for_decision(d)
    assert s.state == "no_evaluado" and "versión anterior" in s.reason


def _pts(n=300):
    return [TimeSeriesPoint(timestamp=f"{2000 + i // 12:04d}-{i % 12 + 1:02d}-01", value=100.0 + i * 0.1)
            for i in range(n)]


def test_etf_catalog_and_default_path_are_not_evaluated():
    etf = EngineSelector.select(_pts(), series_id="SPY", horizon=12)
    assert etf.skill.state == "no_evaluado" and "ETFs" in etf.skill.reason
    default = EngineSelector.select(_pts(), series_id="ZZZZ", horizon=12)   # no db: default path
    assert default.skill.state == "no_evaluado" and "camino por defecto" in default.skill.reason


def test_catalog_series_answered_by_plan_b_is_not_evaluated(monkeypatch):
    monkeypatch.setattr(ad.settings, "USE_REAL_TIMESFM", False)
    res = EngineSelector.select(_pts(), series_id="IPG2211A2N", series_type="macro", horizon=12)
    assert res.is_fallback and res.skill.state == "no_evaluado" and "plan B" in res.skill.reason


def test_catalog_holt_winters_series_uses_the_3_0d_evidence():
    rng = np.random.default_rng(1)
    t = np.arange(240)
    vals = 100 * np.exp(0.002 * t) * (1 + 0.10 * np.sin(2 * np.pi * t / 12)) * np.exp(rng.normal(0, 0.01, 240))
    pts = [TimeSeriesPoint(timestamp=f"{2000 + i // 12:04d}-{i % 12 + 1:02d}-01", value=float(v)) for i, v in enumerate(vals)]
    res = EngineSelector.select(pts, series_id="MRTSSM4451USN", series_type="macro", horizon=12)
    assert res.model_name.startswith("holt-winters")
    assert res.skill.state == "aporta" and res.skill.naive == "naive_estacional" and "3.0d" in res.skill.source
