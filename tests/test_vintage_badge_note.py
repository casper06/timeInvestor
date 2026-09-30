"""3.4 — the provenance note under an "aporta" badge on a revisable SA series.

The badge always measures with TODAY's revised series, without saying so. On a
seasonally adjusted series that gets revised, that flatters the engine: 3.4
found HOUST, INDPRO and JTSJOL keeping their capability with revised data and
losing it with the data as published at the time.
"""
import json
from pathlib import Path

from backend.services.forecast_skill import (
    VINTAGE_EVIDENCE,
    vintage_note,
)

RESULTS = Path("docs/results/vintage_benchmark_2026-09-28.json")


def test_el_snapshot_coincide_con_el_resultado_medido():
    """VINTAGE_EVIDENCE is a snapshot of 3.4's own output, not a hand-written
    list: this recomputes it from the results file, like 4.17 does."""
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    recomputed = {
        sid: bool(v["capability"]["epoca|primera"]["has_capacity"])
        for sid, v in data["series"].items()
    }
    assert recomputed == VINTAGE_EVIDENCE


def test_una_serie_sa_que_no_se_sostuvo_lleva_la_nota():
    note = vintage_note("HOUST", "aporta", "SA")
    assert note is not None
    assert "con datos de época no se sostuvo" in note
    assert "vintage_benchmark_2026-09-28.json" in note


def test_las_tres_series_del_plan_llevan_la_nota():
    for sid in ("HOUST", "INDPRO", "JTSJOL"):
        assert "no se sostuvo" in (vintage_note(sid, "aporta", "SA") or ""), sid


def test_una_sa_no_medida_dice_que_no_se_verifico():
    note = vintage_note("PAYEMS", "aporta", "SA")
    assert note == "Capacidad medida con datos revisados; no verificada con datos de época."


def test_una_sa_que_si_se_sostuvo_no_lleva_nota():
    """Measured and held: nothing to warn about."""
    assert vintage_note("INDPRO", "aporta", "SA") is not None  # this one did NOT hold
    # A series that did hold, forced through the SA branch:
    assert VINTAGE_EVIDENCE["IPG2211A2N"] is True
    assert vintage_note("IPG2211A2N", "aporta", "SA") is None


def test_una_serie_nsa_no_lleva_nota():
    """The revision problem is about seasonal adjustment being restated."""
    assert vintage_note("HOUSTNSA", "aporta", "NSA") is None
    assert vintage_note("HOUST", "aporta", "NSA") is None


def test_sin_metadato_de_ajuste_no_hay_nota():
    """No guessing: with no SA/NSA flag from FRED there is no note."""
    assert vintage_note("HOUST", "aporta", None) is None
    assert vintage_note("HOUST", "aporta", "") is None


def test_no_aporta_y_no_evaluado_no_llevan_nota():
    """Revisions can't make an already-negative verdict worse."""
    assert vintage_note("HOUST", "no_aporta", "SA") is None
    assert vintage_note("HOUST", "no_evaluado", "SA") is None
