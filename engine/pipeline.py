"""One rehearsal run, end to end, without any UI (the app and tests both call this)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from engine.kpis import KPIPack
from engine.llm import LLM
from engine.peers import peers_for
from engine.questions import Question, generate_candidates, rank
from engine.signals import SignalReport, evaluate
from engine.verify import Verification, allowed_numbers, verify_questions


@dataclass
class Rehearsal:
    pack: KPIPack
    report: SignalReport
    top: list[Question] = field(default_factory=list)
    candidates: list[Question] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    held_back: list[Question] = field(default_factory=list)   # failed verification
    verification: Verification = field(default_factory=Verification)
    run_id: str = ""
    ai_calls: int = 0          # how many AI outputs this run recorded (live mode)


def run(llm: LLM, pack: KPIPack, bva: pd.DataFrame | None = None,
        report: SignalReport | None = None, with_peers: bool = True) -> Rehearsal:
    report = report or evaluate(pack)
    r = Rehearsal(pack=pack, report=report, run_id=llm.run_id)
    if not report.flags:
        r.errors.append("No risk signals fired for this quarter, so there is nothing for the board to probe.")
        return r
    r.candidates, r.errors = generate_candidates(llm, pack, report, bva)
    allowed = allowed_numbers(pack, report, bva)
    verify_questions(r.candidates, allowed)
    # A question with a figure that fails verification is never shown as-is.
    clean = [q for q in r.candidates if q.extra["verification"].ok]
    r.held_back = [q for q in r.candidates if not q.extra["verification"].ok]
    r.top = rank(clean, report)
    if r.top and with_peers:   # how peers handled it (retrieval in code, batched AI calls)
        add_peers(llm, r)
    r.ai_calls = llm.cache.count(llm.run_id) if llm.mode == "live" else 0
    r.verification = Verification(checks=[c for q in r.top for c in q.extra["verification"].checks])
    return r


def add_peers(llm: LLM, r: Rehearsal) -> Rehearsal:
    """Second stage, callable separately so the UI can show progress."""
    r.errors += peers_for(llm, r.top, r.pack, r.report)
    r.ai_calls = llm.cache.count(llm.run_id) if llm.mode == "live" else 0
    return r
