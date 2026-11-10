"""Number checker: every figure in AI-written text must trace to a computed number.

The allowed set is built from exactly what the AI was shown: the KPI table, the
trends, the flags' precomputed numbers, budget vs actual and the rule thresholds.

Matching is metric-aware. For each figure, the checker finds the metric the
sentence is talking about (the nearest mention, e.g. "runway", "NRR", "cost of
revenue") and only accepts a computed number *for that metric* with a compatible
unit, within the rounding the figure's own precision implies ("73%" may stand
for 72.8%, "$34.2M" for $34.17M). Thresholds count only when the text refers to
them as such ("below 18 months", "a 3x target"). Anything else is a mismatch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from engine.kpis import METRIC_INFO, KPIPack, trends
from engine.signals import SignalReport, load_rules

UNIT_CAT = {"%": "pct", "pts": "pct", "x": "x", "$M": "usd", "months": "months",
            "logos": "count", "people": "count", "": "count"}

# Column / line item -> metric family.
FAMILY = {
    "arr_m": "arr", "net_new_arr_m": "net_new_arr", "net_new_arr_plan_m": "net_new_arr",
    "revenue_m": "revenue", "nrr_pct": "nrr", "grr_pct": "grr",
    "gross_margin_pct": "gross_margin", "net_burn_m": "net_burn",
    "burn_multiple": "burn_multiple", "equity_raised_m": "equity", "cash_m": "cash",
    "runway_months": "runway", "pipeline_coverage_x": "pipeline",
    "pipeline_target_x": "pipeline", "cac_payback_months": "cac",
    "headcount": "headcount", "enterprise_logos": "logos",
    "Revenue": "revenue", "Cost of revenue (incl. cloud hosting)": "cogs",
    "Gross profit": "gross_profit", "Sales & marketing": "sm",
    "Research & development": "rd", "General & administrative": "ga",
    "Total operating expenses": "opex", "Operating income": "op_income",
    "Other cash items (capex, working capital)": "other_cash", "Net burn": "net_burn",
}
# Words that name each family in prose (longest phrases win).
KEYWORDS = {
    "nrr": ["net revenue retention", "net dollar retention", "net retention", "nrr", "ndr", "expansion",
            "retention"],
    "grr": ["gross revenue retention", "gross retention", "grr", "churn"],
    "gross_margin": ["gross margin", "margin"],
    "burn_multiple": ["burn multiple"],
    "net_burn": ["net burn", "burn rate", "burn"],
    "cash": ["cash", "in the bank"],
    "runway": ["runway"],
    "pipeline": ["pipeline coverage", "pipeline", "coverage"],
    "cac": ["cac payback", "payback", "cac"],
    "headcount": ["headcount", "employees", "people"],
    "logos": ["enterprise logos", "enterprise logo", "enterprise customers", "logos", "logo"],
    "net_new_arr": ["net new arr", "new arr", "bookings", "plan", "forecast"],
    "arr": ["arr"],
    "revenue": ["revenue"],
    "cogs": ["cost of revenue", "cost of goods", "cogs", "hosting", "cloud cost"],
    "gross_profit": ["gross profit"],
    "sm": ["sales & marketing", "sales and marketing", "s&m"],
    "rd": ["research & development", "r&d"],
    "ga": ["general & administrative", "g&a"],
    "opex": ["operating expenses", "opex"],
    "op_income": ["operating income", "operating loss"],
    "other_cash": ["capex", "working capital"],
    "equity": ["raised", "series c"],
}
_KW = sorted(((kw, fam) for fam, kws in KEYWORDS.items() for kw in kws), key=lambda t: -len(t[0]))
KW_RE = re.compile(r"(?<![a-z])(" + "|".join(re.escape(k) for k, _ in _KW) + r")(?![a-z])", re.I)
KW_FAMILY = {k: f for k, f in _KW}

NUM_RE = re.compile(
    r"(?P<dollar>\$)?(?P<num>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"(?:\s|-)?(?P<suffix>%|percentage points?\b|percent\b|pts?\b|points?\b|x\b|×"
    r"|M\b|mm\b|million\b|K\b|k\b|thousand\b|B\b|billion\b|months?\b|mos?\b)?",
    re.I)
IGNORE_RE = re.compile(r"\bQ[1-4](?:\s+(?:FY)?\d{4})?\b|\bFY\s?\d{2,4}\b|\b20\d{2}\b"
                       r"|\bSeries [A-Z]\b|\b\d+(?:st|nd|rd|th)\b|\b\d+\s?(?:seconds?|minutes?)\b"
                       r"|\b(?:week|day|month|step|item|question|bullet)\s+\d+\b",
                       re.I)
TIME_WORDS = re.compile(r"^\s*(?:straight\s+|consecutive\s+)?(quarters?|years?|weeks?|days?|"
                        r"bullets?|questions?|personas?|board members?|of\b)", re.I)
# A threshold is only a legitimate figure when the text calls it one.
REFERENCE_WORDS = re.compile(r"(target|threshold|below|under|above|over|line|floor|ceiling|limit|"
                             r"alert|back to|back under|back above|less than|more than|at least|"
                             r"get to|bring it to|inside|beyond|past|exceed\w*|cross\w*|breach\w*)"
                             r"\W+(?:\w+\W+){0,3}$", re.I)
# ...or the words right after it name it as a reference point ("an 18-month line", "a 3x target").
REFERENCE_AFTER = re.compile(r"^\W*(?:[\w-]+\W+){0,3}?(target|threshold|line|floor|ceiling|limit|bar|"
                             r"trigger|benchmark|alert)\b", re.I)
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_N = r"(\d|two|three|four|five|six|seven|eight)"
# Claims about runs of quarters ("four straight quarters", "each of the last 3 quarters").
STREAK_RE = re.compile(rf"\beach of the (?:last|past) {_N} quarters\b|\b{_N} (?:straight|consecutive) quarters\b"
                       rf"|\b{_N} quarters (?:in a row|running|straight)\b", re.I)
# Sentences end at . ! ? before a capital/number; clauses also end at any semicolon.
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z$\d])|;\s*|\n+")
AFTER_WINDOW = 25   # a metric named after a figure counts only if it is right next to it


@dataclass
class Allowed:
    value: float
    cat: str
    family: str
    source: str
    threshold: bool = False
    delta: bool = False      # a change ("down 9 points"), not a level


@dataclass
class Check:
    text: str
    value: float
    cat: str | None
    ok: bool
    source: str = ""
    family: str | None = None
    context: str = ""


@dataclass
class Verification:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def mismatches(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


# ---- The allowed set --------------------------------------------------------

def allowed_numbers(pack: KPIPack, report: SignalReport, bva: pd.DataFrame | None = None,
                    rules: dict | None = None) -> list[Allowed]:
    out: list[Allowed] = []

    def add(v, cat, fam, src, threshold=False, delta=False):
        if v is not None and not pd.isna(v):
            out.append(Allowed(float(v), cat, fam, src, threshold, delta))

    for _, row in pack.df.iterrows():
        for col, (name, unit) in METRIC_INFO.items():
            if col in row:
                add(row[col], UNIT_CAT.get(unit, "count"), FAMILY[col], f"{name}, {row['quarter']}")

    for _, t in trends(pack).iterrows():
        cat, fam = UNIT_CAT.get(t["unit"], "count"), FAMILY[t["metric"]]
        for k in ("qoq", "yoy"):
            if not pd.isna(t.get(f"{k}_change")):
                add(t[f"{k}_change"], cat, fam, f"{t['name']} {k.upper()} change", delta=True)
            if not pd.isna(t.get(f"{k}_change_pct")):
                add(t[f"{k}_change_pct"], "pct", fam, f"{t['name']} {k.upper()} % change", delta=True)

    for f in report.flags:
        fam = FAMILY.get(f.metric, f.metric)
        metric_cat = UNIT_CAT.get(METRIC_INFO.get(f.metric, ("", ""))[1], "count")
        for k, v in f.numbers.items():
            if k in ("delta", "abs_delta"):
                cat = "pct" if f.unit in ("pts", "%") else UNIT_CAT.get(f.unit, metric_cat)
                if f.unit == "%" and k == "abs_delta":
                    cat = metric_cat
            elif k in ("ratio_pct", "miss_pct") or k.startswith("miss_"):
                cat = "pct"
            elif k == "count":
                continue            # "2 quarters running" is a count, handled by TIME_WORDS
            else:
                cat = metric_cat
            add(v, cat, fam, f"{f.id}.{k}", delta=k in ("delta", "abs_delta"))

    for _, t in trends(pack).iterrows():           # runs of quarters, e.g. margin down 3 in a row
        if t.get("streak"):
            add(abs(t["streak"]), "streak", FAMILY[t["metric"]], f"{t['name']} streak ({int(t['streak']):+d} quarters)")
    for f in report.flags:
        if "count" in f.numbers:
            add(f.numbers["count"], "streak", FAMILY.get(f.metric, f.metric), f"{f.id}.count")

    if bva is not None:
        for _, r in bva.iterrows():
            fam = FAMILY.get(r["line_item"], "other")
            for col in ("budget_m", "actual_m", "variance_m"):
                add(r[col], "usd", fam, f"{r['line_item']} ({col.split('_')[0]}, {r['quarter']})")
            add(r["variance_pct"], "pct", fam, f"{r['line_item']} variance % ({r['quarter']})")

    for r in (rules or load_rules())["rules"]:
        fam = FAMILY.get(r["metric"], r["metric"])
        cat = UNIT_CAT.get(r["unit"], "count")
        for k in ("amber", "red", "positive", "miss_pct"):
            if k in r and not (r["type"] == "consecutive_miss" and k in ("amber", "red")):
                if r["type"] == "vs_target":
                    add(r[k] * 100, "pct", fam, f"{r['id']} {k} threshold", True)
                else:
                    add(r[k], "pct" if k in ("miss_pct", "positive") else cat, fam,
                        f"{r['id']} {k} threshold", True)
    return out


# ---- Extraction -------------------------------------------------------------

def _cat_for(dollar: bool, suffix: str | None) -> tuple[str | None, float]:
    s = (suffix or "").lower()
    if s in ("%", "percent", "pt", "pts", "point", "points") or s.startswith("percentage"):
        return "pct", 1.0
    if s in ("x", "×"):
        return "x", 1.0
    if s in ("m", "mm", "million"):
        return "usd", 1.0
    if s in ("k", "thousand"):
        return "usd", 0.001
    if s in ("b", "billion"):
        return "usd", 1000.0
    if s.startswith("mo"):
        return "months", 1.0
    return ("usd", 1.0) if dollar else (None, 1.0)


@dataclass
class Figure:
    raw: str
    value: float
    cat: str | None
    decimals: int
    start: int
    end: int
    before: str        # text just before the figure (for threshold references)
    after: str = ""    # text just after it


def extract(text: str) -> list[tuple[str, float, str | None, int]]:
    """Return (raw text, value, unit category, decimals) for each figure in text."""
    return [(f.raw, f.value, f.cat, f.decimals) for f in _figures(text)]


def _figures(text: str) -> list[Figure]:
    clean = IGNORE_RE.sub(lambda m: " " * len(m.group(0)), text)
    found = []
    for m in NUM_RE.finditer(clean):
        raw_num = m.group("num").replace(",", "")
        cat, scale = _cat_for(bool(m.group("dollar")), m.group("suffix"))
        value = float(raw_num) * scale
        decimals = len(raw_num.split(".")[1]) if "." in raw_num else 0
        if scale == 0.001:
            decimals += 3
        if cat is None and decimals == 0 and abs(value) <= 12 and TIME_WORDS.match(clean[m.end():]):
            continue  # "two quarters", "3 bullets": counts of things, not figures
        found.append(Figure(m.group(0).strip(), value, cat, decimals, m.start(), m.end(),
                            clean[max(0, m.start() - 40):m.start()], clean[m.end():m.end() + 40]))
    return found


# ---- Matching ---------------------------------------------------------------

def _close(fig: Figure, a: Allowed) -> bool:
    v, av = abs(fig.value), abs(a.value)
    if fig.decimals == 0 and av < 10 and av != round(av):
        return False   # "2x" must not stand in for 2.1x; whole-number rounding only for bigger figures
    return abs(v - av) <= 0.5 * 10 ** (-fig.decimals) + 1e-9


def _referenced(fig: Figure) -> bool:
    return bool(REFERENCE_WORDS.search(fig.before) or REFERENCE_AFTER.search(fig.after))


CHANGE_BEFORE = re.compile(r"(down|up|fell|fall\w*|rose|rise\w*|risen|drop\w*|grew|grow\w*|declin\w*|increas\w*|"
                           r"decreas\w*|lost|los\w*|gain\w*|slipp?\w*|shrank|shrunk|by|swing|moved|add\w*)\W+(?:\w+\W+){0,3}$", re.I)
CHANGE_AFTER = re.compile(r"^\W*(?:[\w-]+\W+){0,2}?(drop|decline|increase|decrease|lower|higher|less|fewer|more|"
                          r"change|swing|gain|loss|improvement|deterioration|up|down|shorter|longer|growth|added|new|net new)\b", re.I)


def _phrased_as_change(fig: Figure) -> bool:
    return fig.raw.lstrip("$").startswith("-") or fig.before.rstrip().endswith("+") or bool(
        CHANGE_BEFORE.search(fig.before) or CHANGE_AFTER.search(fig.after))


def _match_in(fig: Figure, pool: list[Allowed]) -> Allowed | None:
    referenced = _referenced(fig)
    as_change = _phrased_as_change(fig)
    for a in pool:
        if a.threshold and not referenced:
            continue
        if a.delta and not as_change:   # "runway is 11 months" must not match an 11-month drop
            continue
        if _close(fig, a):
            return a
    return None


def _compatible(fig: Figure, a: Allowed) -> bool:
    return fig.cat is None or a.cat == fig.cat


POINT_CHANGE = re.compile(r"(?:pts?|points?)$", re.I)


def verify_text(text: str, allowed: list[Allowed]) -> Verification:
    res = Verification()
    # Metrics the whole card talks about: a "9-point drop" in a sentence that only names
    # GRR may refer to the card's NRR. Used only as a second chance for point changes.
    card_families = {KW_FAMILY[m.group(1).lower()] for m in KW_RE.finditer(text)}
    for sentence in SENTENCE_RE.split(text):
        mentions = [(m.start(), m.end(), KW_FAMILY[m.group(1).lower()]) for m in KW_RE.finditer(sentence)]
        for fig in _figures(sentence):
            # Families mentioned in this sentence: the nearest ones *before* the figure
            # first ("NRR fell to 109%"), then those after it ("$34.17M of cash").
            before = sorted((mm for mm in mentions if mm[1] <= fig.start), key=lambda mm: fig.start - mm[1])
            after = sorted((mm for mm in mentions if fig.end <= mm[0] <= fig.end + AFTER_WINDOW),
                           key=lambda mm: mm[0] - fig.end)   # "40% logo growth", not a later clause
            families = []
            for mm in before + after:
                if mm[2] not in families:
                    families.append(mm[2])
            hit, family = None, None
            for fam in families:
                pool = [a for a in allowed if a.family == fam and _compatible(fig, a)]
                if pool:                         # this metric has numbers of this kind: be strict
                    family, hit = fam, _match_in(fig, pool)
                    break
            if family is None:                   # no metric named for this kind of figure
                hit = _match_in(fig, [a for a in allowed if _compatible(fig, a)])
            if hit is None and _referenced(fig):  # "two misses beyond 10%": a rule's own line
                hit = _match_in(fig, [a for a in allowed if a.threshold and _compatible(fig, a)])
            if hit is None and fig.cat == "pct" and POINT_CHANGE.search(fig.raw):
                hit = _match_in(fig, [a for a in allowed if a.delta and a.cat == "pct"
                                      and a.family in card_families])
            res.checks.append(Check(
                text=fig.raw, value=fig.value, cat=fig.cat, ok=hit is not None, family=family,
                source=hit.source if hit else
                (f"no computed {family.replace('_', ' ')} figure matches" if family
                 else "no matching computed figure"), context=sentence.strip()))
        for m in STREAK_RE.finditer(sentence):
            word = next(g for g in m.groups() if g).lower()
            n = int(word) if word.isdigit() else NUMBER_WORDS[word]
            before = sorted((mm for mm in mentions if mm[1] <= m.start()), key=lambda mm: m.start() - mm[1])
            after = sorted((mm for mm in mentions if mm[0] >= m.end()), key=lambda mm: mm[0] - m.end())
            fams = [mm[2] for mm in before + after]
            fam = fams[0] if fams else None
            pool = [a for a in allowed if a.cat == "streak" and (fam is None or a.family == fam)]
            hit = next((a for a in pool if a.value == n), None)
            res.checks.append(Check(
                text=m.group(0), value=n, cat="streak", ok=hit is not None, family=fam,
                source=hit.source if hit else
                (f"code counts no run of {n} quarters for {fam.replace('_', ' ')}" if fam
                 else f"code counts no run of {n} quarters"), context=sentence.strip()))
    return res


def verify_questions(questions, allowed: list[Allowed]) -> Verification:
    """Verify every AI-written figure on every card; stores per-card results in q.extra."""
    total = Verification()
    for q in questions:
        v = verify_text(q.ai_text, allowed)
        q.extra["verification"] = v
        total.checks += v.checks
    return total
