"""Regression test on REAL model output (Claude Sonnet 5.5, live runs on 2026-11-10).

tests/fixtures/live_cache_2026-11-10.json is the app's own demo-cache export. Every
figure in it was checked by hand against the KPI table and is correct, so the
verifier must accept all of it, and ranking must produce a full, covering top 10.
"""
import shutil

from engine import pipeline
from engine.llm import LLM, DemoCache
from tests.conftest import FIXTURES


def test_real_output_verifies_and_ranks(tmp_path, pack, report, bva):
    cache = tmp_path / "cache.json"
    shutil.copy(FIXTURES / "live_cache_2026-11-10.json", cache)
    llm = LLM(client=None, cache=DemoCache(cache))
    llm.mode = "demo"
    r = pipeline.run(llm, pack, bva, report)
    # This fixture predates the peer layer, so only peer errors (no cached summaries) are expected.
    assert all(e.startswith("Peer") for e in r.errors)
    held = [(m.text, m.context) for q in r.held_back for m in q.extra["verification"].mismatches]
    assert held == []
    assert len(r.top) == 10 and r.verification.ok
    assert {s for q in r.top for s in q.signal_ids} == {f.id for f in report.flags}
    assert len(r.verification.checks) > 90
