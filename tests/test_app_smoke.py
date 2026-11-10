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
    st.cache_resource = lambda f: f
    st.secrets = {}
    st.stop.side_effect = Stop
    st.button.side_effect = lambda label, **kw: buttons.get(label, False)
    st.file_uploader.return_value = None
    st.columns.side_effect = lambda spec: [MagicMock() for _ in (spec if isinstance(spec, list) else range(spec))]
    st.sidebar = MagicMock()
    return st


def test_sample_flow_renders_ten_verified_cards(monkeypatch, tmp_path):
    st = fake_streamlit({"Load Northbeam Q3 board pack": True, "Rehearse": True})
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setattr(engine.llm, "LLM",
                        lambda: LLM(client=FakeClient(), cache=DemoCache(tmp_path / "c.json")))
    runpy.run_path("app.py", run_name="__main__")
    result = st.session_state["result"]
    assert len(result.top) == 10 and result.verification.ok
    assert len(result.held_back) == 1
    st.success.assert_any_call(f"✅ All figures verified: {len(result.verification.checks)} "
                               "numbers checked against the KPI table.")


def test_empty_start_stops_with_a_hint(monkeypatch, tmp_path):
    st = fake_streamlit({})
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setattr(engine.llm, "LLM", lambda: LLM(client=None, cache=DemoCache(tmp_path / "c.json")))
    with pytest.raises(Stop):
        runpy.run_path("app.py", run_name="__main__")
    st.info.assert_called()
