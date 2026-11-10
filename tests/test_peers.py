import json
import shutil
from collections import Counter
from types import SimpleNamespace

import pytest

from engine import pipeline
from engine.peers import (anonymize, coverage, load_library, make_consensus_validator,
                          make_draft_validator, match, tally)
from engine.llm import LLM, DemoCache
from tests.conftest import FIXTURES, FakeClient


# ---- The library ----------------------------------------------------------------

def test_library_shape_and_labels():
    lib = load_library()
    threads = lib["threads"]
    assert 38 <= len(threads) <= 45
    assert len({t["id"] for t in threads}) == len(threads)
    used = {r["approach"] for t in threads for r in t["replies"]}
    assert used == set(lib["approaches"])                      # every tag has a plain-English label
    for t in threads:
        assert t["synthetic"] is True and 3 <= len(t["replies"]) <= 6


def test_library_has_real_disagreement_and_variety():
    threads = load_library()["threads"]
    with_pushback = sum(any(r["dissent"] for r in t["replies"]) for t in threads)
    assert with_pushback >= len(threads) / 3
    stages = {r["stage"] for t in threads for r in t["replies"]}
    industries = {r["industry"] for t in threads for r in t["replies"]}
    assert {"Series B", "Series C", "Series D", "Growth (pre-IPO)"} <= stages
    assert {"Marketplace", "Fintech (payments)", "Vertical SaaS"} <= industries


def test_library_never_mentions_the_company():
    assert "northbeam" not in json.dumps(load_library()).lower()


# ---- Retrieval ------------------------------------------------------------------

def _q(text, sid, why=""):
    return SimpleNamespace(question=text, why_they_ask=why, signal_ids=[sid])


def test_obvious_matches(report):
    hits, _ = match(_q("NRR fell from 118% to 109% while GRR held. Is this expansion or churn?", "NRR_DECLINE"), report)
    assert hits[0].thread_id in {"BT-1001", "BT-1006"}
    hits, _ = match(_q("Net burn was 12% over budget even though opex was on plan. Why?", "BURN_MULTIPLE"), report)
    assert "BT-1017" in [h.thread_id for h in hits]
    hits, _ = match(_q("Cost of revenue ran 10% over budget after the migration. One-off or structural?", "GROSS_MARGIN"), report)
    assert hits[0].thread_id == "BT-1021"


def test_live_questions_never_retrieve_off_topic_threads(pack, report, tmp_path):
    cache = tmp_path / "c.json"
    shutil.copy(FIXTURES / "live_cache_2026-11-10.json", cache)
    llm = LLM(client=None, cache=DemoCache(cache)); llm.mode = "demo"
    r = pipeline.run(llm, pack, None, report)
    off_topic = {t["id"] for t in load_library()["threads"] if t["topic"] == "other"}
    for q in r.candidates:
        hits, _ = match(q, report)
        assert hits, q.question
        assert not off_topic & {h.thread_id for h in hits}
    enterprise = [q for q in r.candidates if q.signal_ids[0] == "ENTERPRISE_LOGOS"]
    assert enterprise and all(coverage(match(q, report)[0]) == "topic" for q in enterprise)


# ---- Code-computed facts -----------------------------------------------------------

def test_tally_counts_replies():
    t = tally(["BT-1001", "BT-1006"])
    assert t["replies"] == 8 and t["threads"] == 2
    top = {a["approach"]: a for a in t["approaches"]}
    assert top["split_churn_vs_expansion"]["replies"] == 3
    assert top["split_churn_vs_expansion"]["thread_ids"] == ["BT-1001", "BT-1006"]
    assert t["pushback_replies"] == 1
    assert sum(a["replies"] for a in t["approaches"]) == t["replies"]


def test_anonymous_ranges(pack, report):
    a = anonymize(pack, report)
    assert a["arr_band"] == "$25–50M ARR" and a["nrr_pct"] == "105–110% NRR"
    assert a["runway_months"] == "12–18 months of runway"
    assert "109" not in json.dumps(a) and "17 months" not in json.dumps(a)


# ---- Guardrails on AI peer text ------------------------------------------------------

@pytest.fixture
def consensus_validator():
    ids = ["BT-1001", "BT-1006"]
    return make_consensus_validator(["Q1"], {"Q1": ids}, {"Q1": tally(ids)})


def _summary(points, split=None):
    return {"summaries": [{"q_id": "Q1", "headline": "Peers split retention first.",
                           "points": points, "split": split, "stage_note": None}]}


def test_consensus_accepts_code_counts_and_quoted_figures(consensus_validator):
    out = consensus_validator(_summary([
        {"text": "3 of 8 replies split retention into churn and expansion.", "thread_ids": ["BT-1001", "BT-1006"]},
        {"text": "One CFO moved from roughly 117% to 109% and showed GRR flat first.", "thread_ids": ["BT-1001"]}]))
    assert len(out["Q1"]["points"]) == 2


def test_consensus_drops_points_citing_threads_it_was_not_given(consensus_validator):
    out = consensus_validator(_summary([
        {"text": "Peers led with cohorts.", "thread_ids": ["BT-1001"]},
        {"text": "Peers cut marketing.", "thread_ids": ["BT-1011"]}]))           # not retrieved for Q1
    assert [p["text"] for p in out["Q1"]["points"]] == ["Peers led with cohorts."]


def test_consensus_drops_invented_counts(consensus_validator):
    out = consensus_validator(_summary([
        {"text": "7 of 9 CFOs led with cohort data.", "thread_ids": ["BT-1001"]},  # code never counted 7 or 9
        {"text": "Peers showed GRR and NRR on one chart.", "thread_ids": ["BT-1006"]}]))
    assert [p["text"] for p in out["Q1"]["points"]] == ["Peers showed GRR and NRR on one chart."]


def test_consensus_with_no_valid_point_is_rejected(consensus_validator):
    with pytest.raises(ValueError, match="no point citing"):
        consensus_validator(_summary([{"text": "Peers agree.", "thread_ids": ["BT-9999"]}]))


@pytest.fixture
def draft_validator(pack, report):
    return make_draft_validator(["Q1"], anonymize(pack, report))


def test_draft_with_ranges_passes(draft_validator):
    out = draft_validator({"drafts": [{"q_id": "Q1", "title": "Proving enterprise growth is quality growth",
        "question": "Series C B2B SaaS, $25–50M ARR, 105–110% NRR, enterprise logos up 40–50% year over year. "
                    "What did you show your board to prove it was repeatable?"}]})
    assert out["Q1"]["title"]


@pytest.mark.parametrize("leak, why", [
    ("We're Northbeam, at 105–110% NRR.", "names the company"),
    ("Our NRR is 109% and runway is 17 months.", "aren't anonymous ranges"),
    ("We have $48M ARR.", "aren't anonymous ranges"),
])
def test_draft_leaks_are_rejected(draft_validator, leak, why):
    with pytest.raises(ValueError, match=why):
        draft_validator({"drafts": [{"q_id": "Q1", "title": "t", "question": leak}]})


# ---- End to end with the stand-in AI ---------------------------------------------

def test_every_card_gets_peers_or_a_draft(fake_llm, pack, report, bva):
    r = pipeline.run(fake_llm, pack, bva, report)
    assert r.errors == [] and len(r.top) == 10
    for q in r.top:
        p = q.extra["peers"]
        if p.coverage == "close":
            assert p.summary and p.summary["points"]
            cited = {t for pt in p.summary["points"] for t in pt["thread_ids"]}
            assert cited <= {m.thread_id for m in p.matches}
        else:
            assert p.draft and "northbeam" not in json.dumps(p.draft).lower()
    consensus_calls = [c for c in fake_llm.client.calls if "summarize how peer CFOs" in c]
    assert 1 <= len(consensus_calls) <= 3                       # batched, not one call per question
