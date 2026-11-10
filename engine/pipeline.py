"""One rehearsal run, end to end, without any UI (the app and tests both call this)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from engine.kpis import KPIPack
from engine.llm import LLM
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


def run(llm: LLM, pack: KPIPack, bva: pd.DataFrame | None = None,
        report: SignalReport | None = None) -> Rehearsal:
    report = report or evaluate(pack)
    r = Rehearsal(pack=pack, report=report)
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
    r.verification = Verification(checks=[c for q in r.top for c in q.extra["verification"].checks])
    return r
