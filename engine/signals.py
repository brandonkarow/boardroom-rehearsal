"""Turn the KPI table into risk flags using the CFO-readable rules in signals.yaml.

Every number a flag mentions is computed here and stored in `flag.numbers`, so
later steps (the AI prompt and the verifier) work from exactly the same figures.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from engine.kpis import METRIC_INFO, KPIPack

RULES_PATH = Path(__file__).resolve().parent.parent / "signals.yaml"
SEVERITY_ORDER = {"red": 0, "amber": 1, "positive": 2}


@dataclass
class Flag:
    id: str
    severity: str                 # red | amber | positive
    label: str
    metric: str
    metric_name: str
    unit: str
    quarter: str
    current: float
    prior: float | None
    prior_quarter: str | None
    delta: float | None
    threshold: str                # the rule line that fired, in words
    description: str
    persona_hint: str
    numbers: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SignalReport:
    flags: list[Flag]
    skipped: list[str]            # rules that couldn't run, and why
    quiet: list[str]              # rules that ran and did not fire

    def by_id(self) -> dict[str, Flag]:
        return {f.id: f for f in self.flags}


def load_rules(path: Path = RULES_PATH) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def fmt(value: float | None, unit: str = "") -> str:
    """Format a number the way a board pack would print it (no trailing zeros)."""
    if value is None:
        return "n/a"
    decimals = 2 if unit in ("x", "$M") else 1
    s = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def with_unit(value: float, unit: str) -> str:
    """'2x', '18 months', '-5 pts', '25%'."""
    return fmt(value, unit) + (unit if unit in ("x", "%") else f" {unit}")


def _signed(value: float, unit: str) -> str:
    s = fmt(value, unit)
    return s if s.startswith("-") or s == "0" else "+" + s


def evaluate(pack: KPIPack, rules: dict | None = None) -> SignalReport:
    rules = rules or load_rules()
    df = pack.df
    flags: list[Flag] = []
    skipped: list[str] = []
    quiet: list[str] = []

    for rule in rules["rules"]:
        rid, metric, rtype = rule["id"], rule["metric"], rule["type"]
        needed = [metric] + [rule[k] for k in ("target_metric", "plan_metric") if k in rule]
        absent = [c for c in needed if c not in df.columns or df[c].isna().all()]
        if absent:
            skipped.append(f"{rid}: column {', '.join(absent)} not in the pack.")
            continue
        lookback = rule.get("lookback", 0)        # hard requirement; compare_lookback is optional
        if lookback and len(df) <= lookback:
            skipped.append(f"{rid}: needs {lookback + 1} quarters of history; the pack has {len(df)}.")
            continue
        if pd.isna(df[metric].iloc[-1]):
            skipped.append(f"{rid}: latest {metric} is blank or undefined.")
            continue

        result = _RULE_TYPES[rtype](df, rule)
        if result is None:
            quiet.append(rid)
            continue
        severity, ctx, threshold = result
        unit = rule["unit"]
        name, metric_unit = METRIC_INFO.get(metric, (metric, unit))
        ctx.setdefault("quarter", pack.quarter)
        text_ctx = {k: (fmt(v, unit if k in ("delta", "abs_delta") else metric_unit)
                        if isinstance(v, (int, float)) else v) for k, v in ctx.items()}
        if "delta" in ctx and isinstance(ctx["delta"], (int, float)):
            text_ctx["delta"] = _signed(ctx["delta"], unit)
            if rule["template"].count("+{delta}"):
                text_ctx["delta"] = text_ctx["delta"].lstrip("+")
        template = rule["template"]
        if ctx.get("prior") is None and "{prior}" in template:   # short history: level only
            template = "{name} is {current}" + ("" if metric_unit in ("logos", "people") else
                                                 ("%" if metric_unit == "%" else
                                                  "x" if metric_unit == "x" else " " + metric_unit)) + " in {quarter}."
            text_ctx["name"] = name
        description = template.format(**text_ctx)
        numbers = {k: float(v) for k, v in ctx.items() if isinstance(v, (int, float))}
        flags.append(Flag(
            id=rid, severity=severity, label=rule["label"], metric=metric,
            metric_name=name, unit=unit, quarter=pack.quarter,
            current=float(ctx["current"]), prior=ctx.get("prior"),
            prior_quarter=ctx.get("prior_quarter"), delta=ctx.get("delta"),
            threshold=threshold, description=description,
            persona_hint=rule.get("persona_hint", ""), numbers=numbers))

    flags.sort(key=lambda f: SEVERITY_ORDER[f.severity])
    return SignalReport(flags=flags, skipped=skipped, quiet=quiet)


# ---- Rule implementations: each returns (severity, context, threshold) or None ----

def _prior(df: pd.DataFrame, metric: str, lookback: int):
    if not lookback or len(df) <= lookback:
        return None, None
    row = df.iloc[-1 - lookback]
    return float(row[metric]), str(row["quarter"])


def _rule_change(df, rule):
    cur = float(df[rule["metric"]].iloc[-1])
    prior, pq = _prior(df, rule["metric"], rule["lookback"])
    delta = round(cur - prior, 2)
    bad = delta if rule["direction"] == "down_is_bad" else -delta
    ctx = {"current": cur, "prior": prior, "prior_quarter": pq,
           "delta": delta, "abs_delta": abs(delta)}
    for sev in ("red", "amber"):
        limit = rule[sev]
        if bad <= limit:
            return sev, ctx, f"{sev}: change of {with_unit(limit, rule['unit'])} or worse over {rule['lookback']} quarters"
    return None


def _rule_level(df, rule):
    cur = float(df[rule["metric"]].iloc[-1])
    prior, pq = _prior(df, rule["metric"], rule.get("compare_lookback", 0))
    ctx = {"current": cur, "prior": prior, "prior_quarter": pq}
    if prior is not None:
        ctx["delta"] = round(cur - prior, 2)
        ctx["abs_delta"] = abs(ctx["delta"])
    up_bad = rule["direction"] == "up_is_bad"
    for sev in ("red", "amber"):
        limit = rule[sev]
        if (cur >= limit) if up_bad else (cur < limit):
            word = "at or above" if up_bad else "below"
            return sev, ctx, f"{sev}: {word} {with_unit(limit, rule['unit'])}"
    return None


def _rule_vs_target(df, rule):
    cur = float(df[rule["metric"]].iloc[-1])
    target = float(df[rule["target_metric"]].iloc[-1])
    if not target or target <= 0 or pd.isna(target):   # no usable target: nothing to compare
        return None
    ratio = cur / target
    ctx = {"current": cur, "target": target, "ratio_pct": round(ratio * 100, 1),
           "delta": round(cur - target, 2)}
    for sev in ("red", "amber"):
        if ratio < rule[sev]:
            return sev, ctx, f"{sev}: below {round(rule[sev] * 100)}% of target"
    return None


def _rule_growth_pct(df, rule):
    cur = float(df[rule["metric"]].iloc[-1])
    prior, pq = _prior(df, rule["metric"], rule["lookback"])
    if not prior:
        return None
    growth = round((cur / prior - 1) * 100, 1)
    ctx = {"current": cur, "prior": prior, "prior_quarter": pq, "delta": growth,
           "abs_delta": round(cur - prior, 2)}
    if growth >= rule["positive"]:
        return "positive", ctx, f"positive: {fmt(rule['positive'])}%+ growth over {rule['lookback']} quarters"
    return None


def _rule_consecutive_miss(df, rule):
    actual, plan = df[rule["metric"]], df[rule["plan_metric"]]
    misses = []
    for i in range(len(df) - 1, -1, -1):
        if pd.isna(plan.iloc[i]) or plan.iloc[i] <= 0:
            break
        miss = round((actual.iloc[i] / plan.iloc[i] - 1) * 100, 1)
        if miss >= -rule["miss_pct"]:
            break
        misses.append((str(df["quarter"].iloc[i]), float(actual.iloc[i]), float(plan.iloc[i]), miss))
    count = len(misses)
    if count < rule["amber"]:
        return None
    misses.reverse()
    detail = "; ".join(f"{q} ${fmt(a, '$M')}M vs ${fmt(p, '$M')}M plan ({fmt(m)}%)" for q, a, p, m in misses)
    ctx = {"current": float(actual.iloc[-1]), "plan": float(plan.iloc[-1]),
           "count": count, "miss_pct": rule["miss_pct"], "miss_detail": detail}
    for j, (q, a, p, m) in enumerate(misses):
        ctx[f"actual_{j}"], ctx[f"plan_{j}"], ctx[f"miss_{j}"] = a, p, m
    sev = "red" if count >= rule["red"] else "amber"
    return sev, ctx, f"{sev}: {rule[sev]}+ consecutive quarters more than {fmt(rule['miss_pct'])}% below plan"


_RULE_TYPES = {
    "change": _rule_change,
    "level": _rule_level,
    "vs_target": _rule_vs_target,
    "growth_pct": _rule_growth_pct,
    "consecutive_miss": _rule_consecutive_miss,
}
