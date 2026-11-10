"""A skeptical CFO's uploads: messy exports, extreme values, and odd sequences."""
import io
import runpy
import sys

import pytest

from data.generate_data import build_kpis
from engine.kpis import SchemaError, load_kpis
from engine.signals import evaluate
from tests.test_app_smoke import fake_streamlit


def _load(df, **kw):
    return load_kpis(io.StringIO(df.to_csv(index=False, **kw)), source="upload")


def test_excel_style_export_parses():
    d = build_kpis().astype(str)
    d["arr_m"] = "$" + d["arr_m"] + "M"
    d["nrr_pct"] = d["nrr_pct"] + "%"
    d["cash_m"] = d["cash_m"].map(lambda v: f"${float(v):,.2f}")
    p = load_kpis(io.BytesIO(("﻿" + d.to_csv(index=False)).encode()), source="upload")
    assert (p.latest.arr_m, p.latest.nrr_pct, p.latest.cash_m) == (48.0, 109.0, 34.17)
    assert len(evaluate(p).flags) == 7


def test_semicolon_csv_parses():
    assert len(evaluate(_load(build_kpis(), sep=";")).flags) == 7


@pytest.mark.parametrize("col, value, phrase", [
    ("nrr_pct", 500, "NRR of 500 looks implausible"),
    ("grr_pct", 130, "GRR can't exceed 100%"),
    ("cash_m", -5, "cash should be positive"),
])
def test_implausible_values_are_flagged_as_data_issues(col, value, phrase):
    d = build_kpis(); d.loc[7, col] = value
    assert any(phrase in i for i in _load(d).issues)


def test_arr_entered_in_dollars_not_millions():
    d = build_kpis(); d["arr_m"] *= 1e6
    assert "ARR should be in $M" in _load(d).issues[0]


def test_zero_pipeline_target_does_not_crash():
    d = build_kpis(); d.loc[7, "pipeline_target_x"] = 0
    assert "PIPELINE_COVERAGE" in evaluate(_load(d)).quiet


def test_negative_net_new_arr_skips_burn_multiple_with_reason():
    d = build_kpis(); d.loc[7, "net_new_arr_m"] = -0.5; d.loc[7, "arr_m"] = d.loc[6, "arr_m"] - 0.5
    p = _load(d)
    assert any("undefined where net new ARR is zero or negative" in i for i in p.issues)
    assert any(s.startswith("BURN_MULTIPLE") for s in evaluate(p).skipped)


@pytest.mark.parametrize("data, phrase", [
    (b"", "Couldn't read that file"),
    (b"PK\x03\x04" + b"\x00" * 64, "missing required column"),
    (b"quarter,arr_m\nQ3 2026,48\n", "missing required column"),
])
def test_unreadable_uploads_get_a_plain_message(data, phrase):
    with pytest.raises(SchemaError, match=phrase):
        load_kpis(io.BytesIO(data), source="upload")


def test_own_pack_without_key_explains_instead_of_failing(monkeypatch):
    """Uploaded CSV, no API key: signals render, Rehearse is disabled with a reason."""
    st = fake_streamlit({"Rehearse": True})
    up = io.BytesIO(build_kpis().iloc[:6].to_csv(index=False).encode()); up.name = "my_pack.csv"
    st.file_uploader.return_value = up
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(Exception):          # the app stops after the Rehearse section (no result yet)
        runpy.run_path("app.py", run_name="__main__")
    assert st.session_state.get("result") is None
    infos = " ".join(str(c.args[0]) for c in st.info.call_args_list)
    assert "only covers the Northbeam sample" in infos and "ANTHROPIC_API_KEY" in infos
    kw = [c.kwargs for c in st.button.call_args_list if c.args and c.args[0] == "Rehearse"][0]
    assert kw["disabled"] is True
