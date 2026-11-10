"""The hard 10: persona calls (AI), then ranking and dedupe (code).

The AI proposes candidate questions; code decides which ten make the cut:
score by signal severity, drop near-duplicates, make sure every flag is covered
(including the positive story), and keep the personas balanced.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from engine.kpis import KPIPack, trends
from engine.llm import LLM, LLMError, read_prompt
from engine.signals import SignalReport, fmt, load_rules

CANDIDATES_PER_PERSONA = 5
TOP_K = 10
MAX_PER_PERSONA = 4
MAX_PER_PRIMARY_SIGNAL = 2    # at most two questions led by the same signal...
MAX_PER_POSITIVE_SIGNAL = 1   # ...and one positive-story question per positive signal
PERSONA_FIT_BONUS = 0.2       # the board member whose lane the signal is in asks it best
DUP_SIMILARITY = 0.5          # TF-IDF cosine at or above this = same question


@dataclass
class Persona:
    id: str
    name: str
    text: str


@dataclass
class Question:
    persona_id: str
    persona_name: str
    question: str
    signal_ids: list[str]
    why_they_ask: str
    answer_outline: list[str]
    trap_to_avoid: str
    score: float = 0.0
    rank: int = 0
    extra: dict = field(default_factory=dict)   # filled later: peers, verification

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def ai_text(self) -> str:
        """All AI-written text on the card (what the verifier checks)."""
        return "\n".join([self.question, self.why_they_ask, *self.answer_outline, self.trap_to_avoid])


# ---- Inputs -----------------------------------------------------------------

def load_personas() -> list[Persona]:
    text = read_prompt("personas.md")
    out = []
    for m in re.finditer(r"^## \[(\w+)\] (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        out.append(Persona(id=m.group(1), name=m.group(2).strip(),
                           text=f"{m.group(2).strip()}\n{m.group(3).strip()}"))
    return out


def thresholds_text(rules: dict | None = None) -> str:
    rules = rules or load_rules()
    lines = []
    for r in rules["rules"]:
        if r["type"] == "growth_pct":
            lines.append(f"{r['id']}: positive at +{fmt(r['positive'])}% over {r['lookback']} quarters")
        elif r["type"] == "consecutive_miss":
            lines.append(f"{r['id']}: a miss is more than {fmt(r['miss_pct'])}% below plan; "
                         f"red at {r['red']} quarters in a row")
        elif r["type"] == "vs_target":
            lines.append(f"{r['id']}: amber below target, red below {round(r['red'] * 100)}% of target")
        else:
            span = f" change over {r['lookback']} quarters" if r["type"] == "change" else ""
            lines.append(f"{r['id']}: amber at {fmt(r['amber'])} {r['unit']}{span}, red at {fmt(r['red'])} {r['unit']}")
    return "\n".join(lines)


def build_context(pack: KPIPack, report: SignalReport, bva: pd.DataFrame | None) -> dict[str, str]:
    signals = [{"id": f.id, "severity": f.severity, "label": f.label,
                "description": f.description,
                "numbers": {k: v for k, v in f.numbers.items()}} for f in report.flags]
    tr = trends(pack)
    return {
        "quarter": pack.quarter,
        "signals": json.dumps(signals, indent=1),
        "trends": tr.to_csv(index=False),
        "thresholds": thresholds_text(),
        "kpi_table": pack.df.to_csv(index=False),
        "n_quarters": str(len(pack.df)),
        "bva": bva.to_csv(index=False) if bva is not None else "(not provided)",
    }


# ---- Validation -------------------------------------------------------------

def make_validator(valid_ids: set[str], persona: Persona):
    def validate(obj) -> list[dict]:
        items = obj["questions"] if isinstance(obj, dict) else obj
        if not isinstance(items, list) or not items:
            raise ValueError("expected a non-empty 'questions' list")
        clean = []
        for q in items:
            ids = [s for s in q.get("signal_ids", []) if s in valid_ids]
            outline = q.get("answer_outline", [])
            if not ids or not str(q.get("question", "")).strip():
                continue          # uncited or empty questions are dropped, never shown
            if not isinstance(outline, list) or len(outline) < 3:
                raise ValueError("each answer_outline must be a list of 3 bullets")
            clean.append({"question": str(q["question"]).strip(), "signal_ids": ids,
                          "why_they_ask": str(q.get("why_they_ask", "")).strip(),
                          "answer_outline": [str(b).strip() for b in outline[:3]],
                          "trap_to_avoid": str(q.get("trap_to_avoid", "")).strip()})
        if not clean:
            raise ValueError("no question cited a valid signal_id from SIGNALS")
        return clean
    return validate


# ---- Generation -------------------------------------------------------------

def generate_candidates(llm: LLM, pack: KPIPack, report: SignalReport,
                        bva: pd.DataFrame | None, n: int = CANDIDATES_PER_PERSONA
                        ) -> tuple[list[Question], list[str]]:
    system = read_prompt("system_prompt.md")
    template = read_prompt("questions.md")
    ctx = build_context(pack, report, bva)
    valid_ids = {f.id for f in report.flags}
    data_key = (pack.df.to_csv(index=False), [f.id for f in report.flags])
    personas = load_personas()

    def ask(p: Persona):
        user = template.format(persona=p.text, n=n, **ctx)
        return llm.json(f"questions/{p.id}", (data_key, n), system, user,
                        make_validator(valid_ids, p))

    # The three board members read the pack at the same time (one call each).
    out, errors = [], []
    with ThreadPoolExecutor(max_workers=len(personas)) as pool:
        futures = [pool.submit(ask, p) for p in personas]
        for p, fut in zip(personas, futures):       # keep persona order stable
            try:
                items = fut.result()
            except LLMError as exc:
                errors.append(f"{p.name}: {exc}")
                continue
            out += [Question(persona_id=p.id, persona_name=p.name, **q) for q in items]
    return out, errors


# ---- Ranking ----------------------------------------------------------------

def score(q: Question, report: SignalReport, weights: dict[str, float]) -> float:
    """Severity of the question's PRIMARY (first-cited) signal, plus small bonuses
    for connecting signals and for asking in the persona's own lane (signals.yaml
    persona_hint). Citing a red signal on the side must not lift a positive-story
    question above the red ones."""
    flags = report.by_id()
    primary = flags[q.signal_ids[0]]
    fit = PERSONA_FIT_BONUS if primary.persona_hint == q.persona_id else 0.0
    return round(weights[primary.severity] + 0.1 * min(len(q.signal_ids) - 1, 2) + fit, 3)


def rank(candidates: list[Question], report: SignalReport, k: int = TOP_K,
         per_persona: int = MAX_PER_PERSONA) -> list[Question]:
    if not candidates:
        return []
    weights = load_rules()["severity_weights"]
    for q in candidates:
        q.score = score(q, report, weights)
    order = sorted(range(len(candidates)), key=lambda i: -candidates[i].score)

    texts = [c.question for c in candidates]
    sim = cosine_similarity(TfidfVectorizer(stop_words="english").fit_transform(texts))

    chosen: list[int] = []
    counts: dict[str, int] = {}
    cap = {f.id: MAX_PER_POSITIVE_SIGNAL if f.severity == "positive" else MAX_PER_PRIMARY_SIGNAL
           for f in report.flags}

    def ok(i: int) -> bool:
        c = candidates[i]
        return (i not in chosen and counts.get(c.persona_id, 0) < per_persona
                and counts.get(c.signal_ids[0], 0) < cap[c.signal_ids[0]]
                and all(sim[i, j] < DUP_SIMILARITY for j in chosen))

    def take(i: int) -> None:
        chosen.append(i)
        for key in (candidates[i].persona_id, candidates[i].signal_ids[0]):
            counts[key] = counts.get(key, 0) + 1

    # 1) Coverage: the best question for each flag, most severe flags first.
    for f in report.flags:
        if len(chosen) >= k or any(f.id in candidates[j].signal_ids for j in chosen):
            continue
        leads = [i for i in order if candidates[i].signal_ids[0] == f.id]
        cites = [i for i in order if f.id in candidates[i].signal_ids[1:]]
        for i in leads + cites:                 # a question *about* the flag beats a passing mention
            if ok(i):
                take(i)
                break
    # 2) Fill by score.
    for i in order:
        if len(chosen) >= k:
            break
        if ok(i):
            take(i)

    top = sorted((candidates[i] for i in chosen), key=lambda c: -c.score)
    for r, q in enumerate(top, 1):
        q.rank = r
    return top
