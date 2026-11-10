import io

import pandas as pd
import pytest

from data.generate_data import build_budget_vs_actual, build_kpis
from engine.kpis import SchemaError, load_kpis, prepare


@pytest.fixture
def sample():
    return load_kpis()


def test_sample_is_eight_quarters_and_reconciles(sample):
    assert list(sample.df["quarter"]) == [
        "Q4 2024", "Q1 2025", "Q2 2025", "Q3 2025",
        "Q4 2025", "Q1 2026", "Q2 2026", "Q3 2026"]
    assert sample.issues == []          # no roll-forward or derived-metric mismatches


def test_committed_csv_matches_generator(sample):
    fresh = build_kpis()
    pd.testing.assert_frame_equal(
        sample.df[fresh.columns].reset_index(drop=True), fresh, check_dtype=False, atol=0.01)


def test_arr_roll_forward(sample):
    df = sample.df
    for i in range(1, len(df)):
        assert df.arr_m[i] - df.arr_m[i - 1] == pytest.approx(df.net_new_arr_m[i], abs=0.01)


def test_runway_is_cash_over_monthly_burn(sample):
    df = sample.df
    assert (df.runway_months - df.cash_m / (df.net_burn_m / 3)).abs().max() < 0.06


def test_burn_multiple_is_burn_over_net_new_arr(sample):
    df = sample.df
    assert (df.burn_multiple - df.net_burn_m / df.net_new_arr_m).abs().max() < 0.006


def test_planted_values(sample):
    df = sample.df.set_index("quarter")
    assert df.loc["Q1 2026", "nrr_pct"] == 118 and df.loc["Q3 2026", "nrr_pct"] == 109
    assert df.loc["Q4 2024", "burn_multiple"] == 1.3 and df.loc["Q3 2026", "burn_multiple"] == 2.1
    assert df.loc["Q3 2025", "gross_margin_pct"] - df.loc["Q3 2026", "gross_margin_pct"] == pytest.approx(3.0)
    assert df.loc["Q3 2026", "pipeline_coverage_x"] == 2.4
    assert df.loc["Q1 2026", "runway_months"] == 22.0 and df.loc["Q3 2026", "runway_months"] == 17.0
    assert df.loc["Q3 2026", "enterprise_logos"] / df.loc["Q3 2025", "enterprise_logos"] == pytest.approx(1.4)
    assert df.loc["Q3 2026", "arr_m"] == 48.0


def test_budget_vs_actual_ties_to_kpis(sample):
    bva = build_budget_vs_actual(build_kpis()).set_index("line_item")
    q3 = sample.latest
    assert bva.loc["Revenue", "actual_m"] == q3.revenue_m
    gm = 1 - bva.loc["Cost of revenue (incl. cloud hosting)", "actual_m"] / q3.revenue_m
    assert gm * 100 == pytest.approx(q3.gross_margin_pct, abs=0.1)
    assert bva.loc["Net burn", "actual_m"] == pytest.approx(q3.net_burn_m, abs=0.01)


def test_missing_column_gives_friendly_error(sample):
    csv = sample.df.drop(columns=["nrr_pct"]).to_csv(index=False)
    with pytest.raises(SchemaError, match="missing required column.*nrr_pct"):
        load_kpis(io.StringIO(csv))


def test_bad_quarter_label():
    df = build_kpis()
    df.loc[0, "quarter"] = "2024-Q4"
    with pytest.raises(SchemaError, match="Q3 2026"):
        prepare(df)


def test_non_numeric_value():
    df = build_kpis().astype({"cash_m": object})
    df.loc[3, "cash_m"] = "about 59"
    with pytest.raises(SchemaError, match="cash_m"):
        prepare(df)


def test_unsorted_quarters_are_sorted():
    df = build_kpis().sample(frac=1, random_state=1)
    assert prepare(df).quarter == "Q3 2026"


def test_wrong_stated_runway_is_reported_and_recomputed():
    df = build_kpis()
    df.loc[7, "runway_months"] = 20.0          # pack claims 20; cash/burn says 17
    pack = prepare(df)
    assert pack.latest.runway_months == 17.0
    assert any("Q3 2026" in i and "runway" in i for i in pack.issues)


def test_broken_arr_roll_forward_is_reported():
    df = build_kpis()
    df.loc[5, "arr_m"] += 1.0
    assert any("Q1 2026: ARR change" in i for i in prepare(df).issues)


def test_garbage_file():
    with pytest.raises(SchemaError):
        load_kpis(io.BytesIO(b"\x00\x01\x02 not a csv"))
