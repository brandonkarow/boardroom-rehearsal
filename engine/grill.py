"""Grill me: answer one board question, get one follow-up and coaching.

Same division of labor as the rest of the app:
- Code checks every figure in the CFO's own answer against the pack and says what the
  pack actually shows ("you said 18 months; runway is 17 months").
- The AI plays the board member (one follow-up) and coaches (1–5 on clarity, use of data,
  root cause). The scores are the AI's judgment and are labeled that way. Any figure the
  AI uses must come from the pack or from the CFO's answer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from engine.kpis import METRIC_INFO, KPIPack, trends
from engine.llm import LLM, data_hash, read_prompt
from engine.questions import load_personas
from engine.signals import SignalReport, fmt
from engine.verify import FAMILY, Allowed, Check, extract, verify_text

SAMPLE_ANSWERS = Path(__file__).resolve().parent.parent / "data" / "sample_answers.json"
DIMENSIONS = [("clarity", "Clarity"), ("use_of_data", "Use of data"), ("root_cause", "Root cause")]
# family -> the KPI column whose current value we quote back to the CFO
FAMILY_COLUMN = {fam: col for col, fam in FAMILY.items() if col in METRIC_INFO and not col.endswith("_plan_m")
                 and col != "pipeline_target_x"}


@dataclass
class AnswerCheck:
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # one plain sentence per mismatch

    @property
    def ok(self) -> bool:
        return not self.notes


def check_answer(answer: str, allowed: list[Allowed], pack: KPIPack) -> AnswerCheck:
    """Code checks the CFO's own figures, and says what the pack shows instead."""
    v = verify_text(answer, allowed)
    out = AnswerCheck(checks=v.checks)
    latest = pack.latest
    for c in v.mismatches:
        col = FAMILY_COLUMN.get(c.family or "")
        if col and col in latest and not pd.isna(latest[col]):
            name, unit = METRIC_INFO[col]
            shown = fmt(float(latest[col]), unit) + ("%" if unit == "%" else "x" if unit == "x"
                                                    else f" {unit}" if unit not in ("$M",) else "")
            if unit == "$M":
                shown = f"${shown}M"
            out.notes.append(f"You said {c.text}; the pack shows {name.lower()} of {shown} in {pack.quarter}.")
        else:
            out.notes.append(f"You said {c.text}; that figure isn't in the board pack.")
    return out


def sample_answer(question_text: str) -> str | None:
    """A written-for-the-demo answer for a sample question, if there is one."""
    try:
        samples = json.loads(SAMPLE_ANSWERS.read_text())["samples"]
    except Exception:
        return None
    return next((s["answer"] for s in samples if question_text.startswith(s["question_starts_with"])), None)


def _validator(allowed: list[Allowed], answer: str):
    answer_numbers = {abs(v) for _, v, _, _ in extract(answer)}

    def validate(obj) -> dict:
        follow = str(obj.get("follow_up", "")).strip()
        if not follow:
            raise ValueError("missing follow_up")
        scores = {}
        for key, _ in DIMENSIONS:
            s = obj.get("scores", {}).get(key, {})
            score = int(s.get("score", 0))
            if not 1 <= score <= 5:
                raise ValueError(f"{key} score must be 1–5")
            scores[key] = {"score": score, "why": str(s.get("why", "")).strip()}
        out = {"follow_up": follow, "scores": scores,
               "strongest": str(obj.get("strongest", "")).strip(), "fix": str(obj.get("fix", "")).strip()}
        text = "\n".join([follow, out["strongest"], out["fix"], *(s["why"] for s in scores.values())])
        bad = [c.text for c in verify_text(text, allowed).mismatches
               if abs(c.value) not in answer_numbers]   # quoting the CFO's own (wrong) figure is fine
        if bad:
            raise ValueError(f"feedback uses figures not in the pack or the answer: {bad}")
        return out
    return validate


def grill(llm: LLM, q, answer: str, pack: KPIPack, report: SignalReport,
          allowed: list[Allowed]) -> tuple[AnswerCheck, dict]:
    persona = next(p for p in load_personas() if p.id == q.persona_id)
    check = check_answer(answer, allowed, pack)
    flags = report.by_id()
    signals = [{"id": s, "description": flags[s].description} for s in q.signal_ids if s in flags]
    user = read_prompt("grill.md").format(
        persona=persona.text, question=q.question,
        signals=json.dumps(signals, indent=1), trends=trends(pack).to_csv(index=False),
        outline="\n".join(f"- {b}" for b in q.answer_outline),
        figure_check="\n".join(check.notes) or "All figures in the answer match the pack.",
        answer=answer.strip() or "(no answer given)")
    out = llm.json(f"grill/{data_hash(q.question)}", (q.question, answer.strip()),
                   read_prompt("system_prompt.md"), user, _validator(allowed, answer))
    return check, out
