import pytest

from data.generate_data import build_kpis
from engine.kpis import load_kpis, prepare
from engine.signals import evaluate, fmt

EXPECTED = {
    "NRR_DECLINE": "red",
    "BURN_MULTIPLE": "red",
    "PIPELINE_COVERAGE": "red",
    "FORECAST_MISS": "red",
    "GROSS_MARGIN": "amber",
    "RUNWAY": "amber",
    "ENTERPRISE_LOGOS": "positive",
}


@pytest.fixture
def report():
    return evaluate(load_kpis())


def test_exactly_the_planted_flags(report):
    assert {f.id: f.severity for f in report.flags} == EXPECTED


def test_watch_list_rules_stay_quiet(report):
    assert set(report.quiet) == {"GRR_DECLINE", "CAC_PAYBACK"}
    assert report.skipped == []


def test_flag_numbers(report):
    f = report.by_id()
    assert (f["NRR_DECLINE"].prior, f["NRR_DECLINE"].current, f["NRR_DECLINE"].delta) == (118, 109, -9)
    assert f["BURN_MULTIPLE"].current == 2.1 and f["BURN_MULTIPLE"].prior == 1.5
    assert f["GROSS_MARGIN"].delta == pytest.approx(-3.0)
    assert f["PIPELINE_COVERAGE"].numbers["ratio_pct"] == 80.0
    assert (f["RUNWAY"].prior, f["RUNWAY"].current) == (22.0, 17.0)
    assert f["ENTERPRISE_LOGOS"].delta == 40.0
    assert f["FORECAST_MISS"].numbers["count"] == 2


def test_every_flag_has_numbers_and_plain_english(report):
    for f in report.flags:
        assert f.description and f.quarter == "Q3 2026"
        assert fmt(f.current, f.unit if f.unit not in ("pts",) else "%") in f.description


def test_descriptions_read_well(report):
    f = report.by_id()
    assert f["NRR_DECLINE"].description == (
        "NRR fell from 118% in Q1 2026 to 109% in Q3 2026 (-9 pts in two quarters).")
    assert "+40% year over year" in f["ENTERPRISE_LOGOS"].description


def test_red_sorted_first(report):
    sev = [f.severity for f in report.flags]
    assert sev == sorted(sev, key=["red", "amber", "positive"].index)


def test_healthy_quarter_has_no_red_flags():
    # Q4 2025 was before the slowdown showed: only the burn multiple was drifting.
    df = build_kpis().iloc[:5]
    ids = {f.id: f.severity for f in evaluate(prepare(df)).flags}
    assert "red" not in ids.values()


def test_short_history_skips_rules_instead_of_crashing():
    rep = evaluate(prepare(build_kpis().iloc[-2:]))
    assert any(s.startswith("GROSS_MARGIN") for s in rep.skipped)
    # Level rules still run without a year-ago comparison.
    assert "BURN_MULTIPLE" not in [s.split(":")[0] for s in rep.skipped]
    bm = rep.by_id()["BURN_MULTIPLE"]
    assert bm.prior is None and bm.description == "Burn multiple is 2.1x in Q3 2026."


def test_missing_optional_column_skips_rule():
    rep = evaluate(prepare(build_kpis().drop(columns=["enterprise_logos"])))
    assert any(s.startswith("ENTERPRISE_LOGOS") for s in rep.skipped)
