"""Smoke test: execute app.py top to bottom against a stand-in for Streamlit.

The build workspace can't install Streamlit, so this checks the script's logic
(every branch the sample flow takes) without rendering anything.
"""
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import engine.llm
from engine.llm import LLM, DemoCache
from tests.conftest import FakeClient


class Stop(Exception):
    pass


class State(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


def fake_streamlit(buttons):
    st = MagicMock()
    st.session_state = State()
    st.secrets = {}
    st.stop.side_effect = Stop
    st.button.side_effect = lambda label, **kw: buttons.get(label, False) and not kw.get("disabled")  # like Streamlit
    st.file_uploader.return_value = None
    st.text_area.side_effect = lambda label, value="", **kw: value          # like Streamlit
    st.form_submit_button.side_effect = lambda label, **kw: buttons.get(label, False)
    st.columns.side_effect = lambda spec: [MagicMock() for _ in (spec if isinstance(spec, list) else range(spec))]
    st.sidebar = MagicMock()
    return st


def test_sample_flow_renders_ten_verified_cards(monkeypatch, tmp_path):
    st = fake_streamlit({"Load Northbeam Q3 board pack": True, "Rehearse": True})
    monkeypatch.setitem(sys.modules, "streamlit", st)
    st.radio.return_value = "Live AI run"
    monkeypatch.setattr(engine.llm, "LLM",
                        lambda **kw: LLM(client=kw.get("client", FakeClient()), cache=DemoCache(tmp_path / "c.json")))
    runpy.run_path("app.py", run_name="__main__")
    result = st.session_state["result"]
    assert len(result.top) == 10 and result.verification.ok
    assert len(result.held_back) == 1
    st.success.assert_any_call(f"✅ All figures verified: {len(result.verification.checks)} "
                               "numbers checked against the KPI table.")


def test_empty_start_stops_with_a_hint(monkeypatch, tmp_path):
    st = fake_streamlit({})
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setattr(engine.llm, "LLM", lambda **kw: LLM(client=None, cache=DemoCache(tmp_path / "c.json")))
    with pytest.raises(Stop):
        runpy.run_path("app.py", run_name="__main__")
    st.info.assert_called()


def test_reviewer_path_instant_demo_with_committed_cache(monkeypatch):
    """No key, sample pack, Rehearse: the full experience from demo_cache/cache.json."""
    st = fake_streamlit({"Load Northbeam Q3 board pack": True, "Rehearse": True})
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runpy.run_path("app.py", run_name="__main__")
    result = st.session_state["result"]
    assert result.errors == [] and len(result.top) == 10 and result.verification.ok
    assert all(q.extra["peers"].summary for q in result.top)


def _demo_cache_has_grill():
    import json
    from engine.llm import CACHE_PATH
    return any(k.startswith("grill/") for k in json.loads(CACHE_PATH.read_text()))


@pytest.mark.skipif(not _demo_cache_has_grill(), reason="saved Grill me exchange not in demo_cache yet")
def test_grill_me_demo_replays_the_saved_exchange(monkeypatch):
    """Demo mode, card #1, sample answer: code flags the wrong runway figure, the board
    member's follow-up and coaching come from the saved live exchange."""
    st = fake_streamlit({"Load Northbeam Q3 board pack": True, "Rehearse": True, "Answer the board": True})
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runpy.run_path("app.py", run_name="__main__")
    grilled = {k: v for k, v in st.session_state.items() if k.startswith("grill_1_")}
    assert len(grilled) == 1, list(st.session_state)
    check, out = next(iter(grilled.values()))
    assert check.notes == ["You said 18 months; the pack shows runway of 17 months in Q3 2026."]
    assert out["follow_up"] and all(1 <= out["scores"][k]["score"] <= 5 for k in ("clarity", "use_of_data", "root_cause"))
