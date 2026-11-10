import json
import re
from pathlib import Path

import pytest

from engine.kpis import load_budget_vs_actual, load_kpis
from engine.llm import LLM, DemoCache
from engine.signals import evaluate

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Stands in for the Anthropic API: answers each persona from the fixture file."""
    model = "fake-model"

    def __init__(self, replies: dict | None = None, broken_first: bool = False):
        self.replies = replies or json.loads((FIXTURES / "fake_candidates.json").read_text())
        self.broken_first = broken_first
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append(user)
        if self.broken_first and len(self.calls) == 1:
            return "Sure! Here are the questions you asked for: {oops"
        persona = next(pid for pid in ("growth_vc", "independent_director", "cash_investor")
                       if re.search(rf"\[{pid}\]|^{self._name(pid)}", user, re.M))
        return "```json\n" + json.dumps(self.replies[persona]) + "\n```"

    @staticmethod
    def _name(pid):
        return {"growth_vc": "The Growth VC", "independent_director": "The Skeptical Independent Director",
                "cash_investor": "The Cash-Focused Lead Investor"}[pid]


@pytest.fixture
def pack():
    return load_kpis()


@pytest.fixture
def report(pack):
    return evaluate(pack)


@pytest.fixture
def bva():
    return load_budget_vs_actual()


@pytest.fixture
def fake_llm(tmp_path):
    return LLM(client=FakeClient(), cache=DemoCache(tmp_path / "cache.json"))
