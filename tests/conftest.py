import json
import re
from pathlib import Path

import pytest

from engine.kpis import load_budget_vs_actual, load_kpis
from engine.llm import LLM, DemoCache
from engine.signals import evaluate

FIXTURES = Path(__file__).parent / "fixtures"


def _between(text, start, end):
    i = text.index(start) + len(start)
    return json.loads(text[i:text.index(end, i)])


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
        if "summarize how peer CFOs" in user:
            return json.dumps(self.consensus_reply(_between(user, "INPUT\n", "\n\nOUTPUT")))
        if "draft a short\nquestion the CFO could post" in user:
            return json.dumps(self.draft_reply(_between(user, "ANONYMOUS_FACTS (computed by code)\n", "\n\nQUESTIONS"),
                                               _between(user, "QUESTIONS\n", "\n\nOUTPUT")))
        persona = next(pid for pid in ("growth_vc", "independent_director", "cash_investor")
                       if re.search(rf"\[{pid}\]|^{self._name(pid)}", user, re.M))
        return "```json\n" + json.dumps(self.replies[persona]) + "\n```"

    @staticmethod
    def consensus_reply(payload):
        out = []
        for q in payload:
            top = q["approach_counts"]["approaches"][0]
            t0 = q["threads"][0]["thread_id"]
            out.append({"q_id": q["q_id"], "headline": f"Peers {top['label']}.",
                        "points": [{"approach": top["approach"], "text": f"Peers {top['label']}.",
                                    "thread_ids": top["thread_ids"]},
                                   {"approach": None, "text": "One peer tied it to a dated plan.", "thread_ids": [t0]}],
                        "split": None, "stage_note": None})
        return {"summaries": out}

    @staticmethod
    def draft_reply(anon, payload):
        return {"drafts": [{"q_id": q["q_id"], "title": "How did you prove enterprise growth was quality growth?",
                            "question": f"We're a {anon['stage']} {anon['company']} company at {anon['arr_band']} "
                                        f"with {anon['nrr_pct']}. How did you show the board it was repeatable?"}
                           for q in payload]}

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
