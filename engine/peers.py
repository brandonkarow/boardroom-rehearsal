"""How peers handled it: thread retrieval, code-counted approaches, consensus and
Braintrust drafts.

Division of labor (same rule as the rest of the app):
- Code finds the threads (TF-IDF), counts which approaches peers took, and turns the
  company's numbers into anonymous ranges.
- The AI only writes sentences from those inputs, citing thread IDs. Code rejects any
  citation to a thread it didn't retrieve, any count it didn't compute, and any
  Braintrust draft that leaks the company name or an exact figure.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from engine.kpis import KPIPack
from engine.llm import LLM, LLMError, data_hash, read_prompt
from engine.signals import SignalReport, load_rules
from engine.verify import extract

THREADS_PATH = Path(__file__).resolve().parent.parent / "data" / "peer_threads.json"
TOP_THREADS = 3
MATCH_THRESHOLD = 0.25     # best thread must score this (query + topic boost); tuned on live questions
SECOND_FLOOR = 0.22        # 2nd/3rd threads: at least this, or half the best score, whichever is lower
DIRECT_CLOSE = 0.12        # question text alone vs best thread: below this, peers covered the topic,
                           # not this exact question, so we also draft a Braintrust question
RELATIVE_FLOOR = 0.5
DIRECT_WEIGHT = 0.5        # weight of the question's own words in the ranking
TOPIC_BOOST = 0.08         # added when a thread's topic matches the main signal's peer_topic
BATCH_SIZE = 4             # questions per consensus call; batches run in parallel
COMPANY_NAMES = ["northbeam"]


# ---- Library ------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_library() -> dict:
    return json.loads(THREADS_PATH.read_text())


def threads_by_id() -> dict[str, dict]:
    return {t["id"]: t for t in load_library()["threads"]}


def _thread_doc(t: dict) -> str:
    # Title, question and tags carry the topic; tags count twice. Replies add vocabulary.
    return " ".join([t["title"], t["question"], " ".join(t["tags"]) * 2,
                     " ".join(r["text"] for r in t["replies"])])


@lru_cache(maxsize=1)
def _index():
    threads = load_library()["threads"]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
    matrix = vec.fit_transform([_thread_doc(t) for t in threads])
    return vec, matrix, threads


# ---- Retrieval ----------------------------------------------------------------

@dataclass
class Match:
    thread_id: str
    title: str
    score: float           # query (question + main signal keywords) + topic boost
    direct: float = 0.0    # the question's own words vs this thread


def query_text(question, report: SignalReport) -> str:
    """The question, plus the CFO-readable peer_keywords of the signals it cites."""
    kw = {r["id"]: r.get("peer_keywords", "") for r in load_rules()["rules"]}
    flags = report.by_id()
    primary = question.signal_ids[0]
    # The main signal's words count twice; secondary signals don't add keywords, or a
    # passing mention ("...and margin") would pull in the wrong topic.
    parts = [question.question, question.why_they_ask, kw.get(primary, ""), kw.get(primary, ""),
             flags[primary].label if primary in flags else ""]
    return " ".join(parts)


def match(question, report: SignalReport, k: int = TOP_THREADS,
          threshold: float = MATCH_THRESHOLD) -> tuple[list[Match], float]:
    """Top-k threads, and the best score seen (for display).

    The best thread must clear `threshold`; the next ones must clear the lower of
    SECOND_FLOOR and half the best score, so a near-identical thread doesn't crowd
    out reasonable second opinions."""
    vec, matrix, threads = _index()
    sims = cosine_similarity(vec.transform([query_text(question, report)]), matrix)[0]
    topic = {r["id"]: r.get("peer_topic") for r in load_rules()["rules"]}.get(question.signal_ids[0])
    sims = sims + [TOPIC_BOOST if t["topic"] == topic else 0.0 for t in threads]
    direct = cosine_similarity(vec.transform([question.question]), matrix)[0]
    sims = sims + DIRECT_WEIGHT * direct   # the question's own wording also ranks threads
    order = sims.argsort()[::-1]
    best = float(sims[order[0]])
    if best < threshold:
        return [], round(best, 3)
    floor = max(threshold * 0.5, min(SECOND_FLOOR, RELATIVE_FLOOR * best))
    hits = [Match(threads[i]["id"], threads[i]["title"], round(float(sims[i]), 3), round(float(direct[i]), 3))
            for n, i in enumerate(order[:k]) if n == 0 or sims[i] >= floor]
    return hits, round(best, 3)


def coverage(hits: list[Match]) -> str:
    """'close' = peers discussed this question; 'topic' = the area, not this exact
    question; 'none' = nothing relevant."""
    if not hits:
        return "none"
    return "close" if max(h.direct for h in hits) >= DIRECT_CLOSE else "topic"


# ---- Code-computed facts ---------------------------------------------------------

def tally(thread_ids: list[str]) -> dict:
    """Count approaches across the replies in the matched threads."""
    lib, by_id = load_library(), threads_by_id()
    replies = [(tid, r) for tid in thread_ids for r in by_id[tid]["replies"]]
    counts = Counter(r["approach"] for _, r in replies)
    approaches = []
    for appr, n in counts.most_common():
        tids = sorted({tid for tid, r in replies if r["approach"] == appr})
        approaches.append({"approach": appr, "label": lib["approaches"][appr],
                           "replies": n, "of": len(replies), "thread_ids": tids})
    stages = Counter(r["stage"] for _, r in replies)
    return {
        "replies": len(replies),
        "threads": len(thread_ids),
        "pushback_replies": sum(r.get("dissent", False) for _, r in replies),
        "approaches": approaches,
        "stages": dict(stages.most_common()),
    }


def _band(value: float, step: float) -> tuple[float, float]:
    lo = math.floor(value / step) * step
    return round(lo, 2), round(lo + step, 2)


def anonymize(pack: KPIPack, report: SignalReport) -> dict[str, str]:
    """The company's situation as ranges, safe to post to peers."""
    row = pack.latest
    arr = float(row["arr_m"])
    arr_band = next(b for lo, hi, b in [(0, 10, "under $10M"), (10, 25, "$10–25M"), (25, 50, "$25–50M"),
                                        (50, 100, "$50–100M"), (100, 1e9, "$100M+")] if lo <= arr < hi)
    # The sample is a Series C company; an uploaded pack has no stage column, so stay generic.
    stage = "Series C" if pack.source == "sample" else "venture-backed"
    facts = {"stage": stage, "company": "B2B SaaS", "arr_band": arr_band + " ARR"}
    spec = {"nrr_pct": (5, "{}–{}% NRR"), "grr_pct": (5, "{}–{}% GRR"),
            "gross_margin_pct": (5, "{}–{}% gross margin"), "burn_multiple": (0.5, "{}–{}x burn multiple"),
            "runway_months": (6, "{}–{} months of runway"), "pipeline_coverage_x": (0.5, "{}–{}x pipeline coverage")}
    for col, (step, tmpl) in spec.items():
        if col in row and not math.isnan(float(row[col])):
            lo, hi = _band(float(row[col]), step)
            fmt = lambda v: f"{v:g}"
            facts[col] = tmpl.format(fmt(lo), fmt(hi))
    f = report.by_id()
    if "FORECAST_MISS" in f:
        worst = min(v for k, v in f["FORECAST_MISS"].numbers.items() if k.startswith("miss_"))
        lo, hi = _band(abs(worst), 5)
        facts["plan_miss"] = f"missed plan by {lo:g}–{hi:g}% for {int(f['FORECAST_MISS'].numbers['count'])} quarters"
    if "ENTERPRISE_LOGOS" in f:
        lo, hi = _band(f["ENTERPRISE_LOGOS"].delta, 10)
        facts["enterprise_logos"] = f"enterprise logos up {lo:g}–{hi:g}% year over year"
    return facts


# ---- Results ------------------------------------------------------------------

@dataclass
class PeerResult:
    matches: list[Match]
    best_score: float
    facts: dict | None = None            # code-computed tally (matched questions)
    summary: dict | None = None          # AI: headline, points, split, stage_note
    draft: dict | None = None            # AI: anonymous Braintrust question (no match)
    problems: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return bool(self.matches)

    @property
    def coverage(self) -> str:
        return coverage(self.matches)


def _numbers_in(text: str) -> set[float]:
    return {abs(v) for _, v, _, _ in extract(text)}


def _allowed_peer_numbers(thread_ids: list[str], facts: dict) -> set[float]:
    by_id = threads_by_id()
    nums = {float(facts["replies"]), float(facts["threads"]), float(facts["pushback_replies"])}
    for a in facts["approaches"]:
        nums |= {float(a["replies"]), float(a["of"]), float(len(a["thread_ids"]))}
    nums |= {float(n) for n in facts["stages"].values()}
    for tid in thread_ids:
        nums |= _numbers_in(_thread_doc(by_id[tid]))
    return nums


def _check_numbers(text: str, allowed: set[float]) -> list[str]:
    return [raw for raw, v, _, _ in extract(text) if not any(abs(abs(v) - a) < 1e-6 for a in allowed)]


def make_consensus_validator(qids: list[str], allowed_threads: dict[str, list[str]],
                             facts: dict[str, dict]):
    def validate(obj) -> dict:
        items = obj["summaries"] if isinstance(obj, dict) else obj
        out = {}
        for s in items:
            qid = str(s.get("q_id"))
            if qid not in allowed_threads:
                continue
            ok_ids = set(allowed_threads[qid])
            allowed_nums = _allowed_peer_numbers(allowed_threads[qid], facts[qid])
            points = []
            for p in s.get("points", []):
                ids = [t for t in p.get("thread_ids", []) if t in ok_ids]
                text = str(p.get("text", "")).strip()
                if ids and text and not _check_numbers(text, allowed_nums):
                    points.append({"text": text, "thread_ids": ids})
            if not points:
                raise ValueError(f"summary for {qid} has no point citing a retrieved thread with valid counts")
            split = s.get("split")
            if split:
                ids = [t for t in split.get("thread_ids", []) if t in ok_ids]
                text = str(split.get("text", "")).strip()
                split = {"text": text, "thread_ids": ids} if ids and text and not _check_numbers(text, allowed_nums) else None
            headline = str(s.get("headline", "")).strip()
            if _check_numbers(headline, allowed_nums):
                headline = ""
            note = s.get("stage_note")
            note = str(note).strip() if note and not _check_numbers(str(note), allowed_nums) else None
            out[qid] = {"headline": headline, "points": points, "split": split, "stage_note": note}
        missing = [q for q in qids if q not in out]
        if missing:
            raise ValueError(f"missing summaries for {missing}")
        return out
    return validate


def make_draft_validator(qids: list[str], anon: dict[str, str]):
    band_numbers = set().union(*(_numbers_in(v) for v in anon.values())) if anon else set()

    def validate(obj) -> dict:
        items = obj["drafts"] if isinstance(obj, dict) else obj
        out = {}
        for d in items:
            qid = str(d.get("q_id"))
            title, body = str(d.get("title", "")).strip(), str(d.get("question", "")).strip()
            text = f"{title} {body}"
            if qid not in qids or not body:
                continue
            if any(n in text.lower() for n in COMPANY_NAMES):
                raise ValueError(f"draft {qid} names the company")
            leaked = [raw for raw, v, _, _ in extract(text) if abs(v) not in band_numbers]
            if leaked:
                raise ValueError(f"draft {qid} uses figures that aren't anonymous ranges: {leaked}")
            out[qid] = {"title": title, "question": body}
        missing = [q for q in qids if q not in out]
        if missing:
            raise ValueError(f"missing drafts for {missing}")
        return out
    return validate


# ---- Orchestration -------------------------------------------------------------

def _thread_block(tid: str) -> dict:
    t = threads_by_id()[tid]
    return {"thread_id": tid, "title": t["title"], "asked_by": t["asked_by"], "question": t["question"],
            "replies": [{"stage": r["stage"], "industry": r["industry"], "approach": r["approach"],
                         "pushback": r.get("dissent", False), "text": r["text"]} for r in t["replies"]]}


def peers_for(llm: LLM, questions: list, pack: KPIPack, report: SignalReport) -> list[str]:
    """Fill q.extra['peers'] for each question. Returns user-facing error messages."""
    errors: list[str] = []
    system = read_prompt("system_prompt.md")
    results = {}
    for q in questions:
        hits, best = match(q, report)
        results[f"Q{q.rank}"] = PeerResult(matches=hits, best_score=best,
                                           facts=tally([h.thread_id for h in hits]) if hits else None)
        q.extra["peers"] = results[f"Q{q.rank}"]

    matched = [q for q in questions if results[f"Q{q.rank}"].matched]
    # Braintrust drafts where peers haven't discussed this exact question.
    unmatched = [q for q in questions if results[f"Q{q.rank}"].coverage != "close"]
    anon = anonymize(pack, report)
    data_key = (pack.df.to_csv(index=False),)

    def consensus(batch):
        qids = [f"Q{q.rank}" for q in batch]
        payload = [{"q_id": f"Q{q.rank}", "question": q.question,
                    "approach_counts": results[f"Q{q.rank}"].facts,
                    "threads": [_thread_block(m.thread_id) for m in results[f"Q{q.rank}"].matches]}
                   for q in batch]
        user = read_prompt("consensus.md").format(payload=json.dumps(payload, indent=1, ensure_ascii=False))
        allowed = {f"Q{q.rank}": [m.thread_id for m in results[f"Q{q.rank}"].matches] for q in batch}
        facts = {f"Q{q.rank}": results[f"Q{q.rank}"].facts for q in batch}
        key = (data_key, [(p["q_id"], p["question"], allowed[p["q_id"]]) for p in payload])
        return llm.json(f"consensus/{data_hash(qids)}", key, system, user,
                        make_consensus_validator(qids, allowed, facts))

    def drafts(batch):
        qids = [f"Q{q.rank}" for q in batch]
        payload = [{"q_id": f"Q{q.rank}", "question": q.question} for q in batch]
        user = read_prompt("braintrust.md").format(
            anon=json.dumps(anon, indent=1, ensure_ascii=False),
            payload=json.dumps(payload, indent=1, ensure_ascii=False))
        key = (data_key, [(p["q_id"], p["question"]) for p in payload])
        return llm.json(f"braintrust/{data_hash(qids)}", key, system, user,
                        make_draft_validator(qids, anon))

    jobs = [("consensus", matched[i:i + BATCH_SIZE]) for i in range(0, len(matched), BATCH_SIZE)]
    if unmatched:
        jobs.append(("drafts", unmatched))
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        futures = [(kind, batch, pool.submit(consensus if kind == "consensus" else drafts, batch))
                   for kind, batch in jobs]
        for kind, batch, fut in futures:
            try:
                out = fut.result()
            except LLMError as exc:
                errors.append(f"Peer {'summaries' if kind == 'consensus' else 'Braintrust drafts'}: {exc}")
                continue
            except Exception as exc:
                errors.append(f"Peer layer: unexpected error ({exc.__class__.__name__}).")
                continue
            for q in batch:
                r = results[f"Q{q.rank}"]
                if kind == "consensus":
                    r.summary = out[f"Q{q.rank}"]
                else:
                    r.draft = out[f"Q{q.rank}"]
    return errors
