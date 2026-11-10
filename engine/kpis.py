"""Load a board KPI pack, check its schema, and recompute derived metrics.

Code is the source of truth for every number: burn multiple and runway are
recomputed from their inputs, and the ARR and cash roll-forwards are checked.
Any disagreement with the uploaded figures is reported, never silently used.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Union

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_KPIS = ROOT / "data" / "northbeam_board_kpis.csv"
SAMPLE_BVA = ROOT / "data" / "northbeam_budget_vs_actual.csv"

REQUIRED_COLUMNS = [
    "quarter", "arr_m", "net_new_arr_m", "nrr_pct", "grr_pct", "gross_margin_pct",
    "net_burn_m", "cash_m", "pipeline_coverage_x",
]
OPTIONAL_COLUMNS = [
    "net_new_arr_plan_m", "revenue_m", "burn_multiple", "equity_raised_m",
    "runway_months", "pipeline_target_x", "cac_payback_months", "headcount",
    "enterprise_logos",
]
DEFAULT_PIPELINE_TARGET_X = 3.0

# Human-readable names and units, used by the UI, the brief and the verifier.
METRIC_INFO = {
    "arr_m": ("ARR", "$M"),
    "net_new_arr_m": ("Net new ARR", "$M"),
    "net_new_arr_plan_m": ("Net new ARR plan", "$M"),
    "revenue_m": ("Revenue (quarter)", "$M"),
    "nrr_pct": ("NRR", "%"),
    "grr_pct": ("GRR", "%"),
    "gross_margin_pct": ("Gross margin", "%"),
    "net_burn_m": ("Net burn (quarter)", "$M"),
    "burn_multiple": ("Burn multiple", "x"),
    "equity_raised_m": ("Equity raised", "$M"),
    "cash_m": ("Cash", "$M"),
    "runway_months": ("Runway", "months"),
    "pipeline_coverage_x": ("Pipeline coverage (next qtr)", "x"),
    "pipeline_target_x": ("Pipeline coverage target", "x"),
    "cac_payback_months": ("CAC payback", "months"),
    "headcount": ("Headcount", "people"),
    "enterprise_logos": ("Enterprise logos", "logos"),
}

QUARTER_RE = re.compile(r"^Q([1-4])\s+(\d{4})$")
MIN_QUARTERS = 2
TOL_RATIO = 0.05   # burn multiple tolerance (x)
TOL_MONTHS = 0.5   # runway tolerance (months)
TOL_M = 0.05       # $M tolerance for roll-forwards


class SchemaError(ValueError):
    """Raised with a message that is safe to show a CFO in the UI."""


@dataclass
class KPIPack:
    df: pd.DataFrame
    issues: list[str] = field(default_factory=list)   # reconciliation / data notes
    source: str = "sample"

    @property
    def latest(self) -> pd.Series:
        return self.df.iloc[-1]

    @property
    def quarter(self) -> str:
        return str(self.latest["quarter"])


def _quarter_key(q: str) -> int:
    m = QUARTER_RE.match(q)
    return int(m.group(2)) * 4 + int(m.group(1))


def load_kpis(src: Union[str, Path, IO, None] = None, source: str | None = None) -> KPIPack:
    """Load a KPI CSV (path or file-like). Defaults to the Northbeam sample."""
    src = SAMPLE_KPIS if src is None else src
    try:
        raw = pd.read_csv(src)
    except Exception as exc:  # malformed file, wrong encoding, empty upload...
        raise SchemaError(f"Couldn't read that file as a CSV ({exc.__class__.__name__}).") from exc
    return prepare(raw, source=source or ("sample" if src == SAMPLE_KPIS else "upload"))


def prepare(raw: pd.DataFrame, source: str = "upload") -> KPIPack:
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(
            "The board pack is missing required column(s): " + ", ".join(missing)
            + ". Required: " + ", ".join(REQUIRED_COLUMNS) + ".")

    df["quarter"] = df["quarter"].astype(str).str.strip()
    bad_q = [q for q in df["quarter"] if not QUARTER_RE.match(q)]
    if bad_q:
        raise SchemaError(f"Quarter labels must look like 'Q3 2026'; found: {', '.join(bad_q[:3])}.")
    if df["quarter"].duplicated().any():
        raise SchemaError("Each quarter must appear once; found duplicates.")
    if len(df) < MIN_QUARTERS:
        raise SchemaError(f"Need at least {MIN_QUARTERS} quarters of data to compute trends.")

    numeric = [c for c in REQUIRED_COLUMNS + OPTIONAL_COLUMNS if c in df.columns and c != "quarter"]
    for c in numeric:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    blanks = [c for c in REQUIRED_COLUMNS[1:] if df[c].isna().any()]
    if blanks:
        raise SchemaError("These columns have blank or non-numeric values: " + ", ".join(blanks) + ".")

    df = df.sort_values("quarter", key=lambda s: s.map(_quarter_key)).reset_index(drop=True)
    issues: list[str] = []

    if "pipeline_target_x" not in df.columns:
        df["pipeline_target_x"] = DEFAULT_PIPELINE_TARGET_X
        issues.append(f"No pipeline target column; assumed {DEFAULT_PIPELINE_TARGET_X}x.")
    if "equity_raised_m" not in df.columns:
        df["equity_raised_m"] = 0.0
    df["equity_raised_m"] = df["equity_raised_m"].fillna(0.0)

    # --- Recompute derived metrics; report any disagreement with the pack ---
    calc_bm = (df["net_burn_m"] / df["net_new_arr_m"].where(df["net_new_arr_m"] > 0)).round(2)
    calc_rw = (df["cash_m"] / (df["net_burn_m"].where(df["net_burn_m"] > 0) / 3)).round(1)
    for col, calc, tol, unit in [("burn_multiple", calc_bm, TOL_RATIO, "x"),
                                 ("runway_months", calc_rw, TOL_MONTHS, " months")]:
        if col in df.columns:
            diff = (df[col] - calc).abs()
            for i in df.index[diff > tol]:
                issues.append(
                    f"{df.loc[i, 'quarter']}: stated {METRIC_INFO[col][0].lower()} {df.loc[i, col]}{unit} "
                    f"doesn't match the recomputed {calc[i]}{unit}; using the recomputed value.")
        df[col] = calc
    if (df["net_new_arr_m"] <= 0).any():
        issues.append("Burn multiple is undefined where net new ARR is zero or negative.")
    if (df["net_burn_m"] <= 0).any():
        issues.append("Runway is undefined (cash-flow positive) where net burn is zero or negative.")

    # --- Roll-forward checks ---
    for i in range(1, len(df)):
        q = df.loc[i, "quarter"]
        arr_gap = df.loc[i, "arr_m"] - df.loc[i - 1, "arr_m"] - df.loc[i, "net_new_arr_m"]
        if abs(arr_gap) > TOL_M:
            issues.append(f"{q}: ARR change doesn't equal net new ARR (off by ${arr_gap:+.2f}M).")
        cash_gap = (df.loc[i, "cash_m"] - df.loc[i - 1, "cash_m"]
                    + df.loc[i, "net_burn_m"] - df.loc[i, "equity_raised_m"])
        if abs(cash_gap) > TOL_M:
            issues.append(f"{q}: cash change doesn't equal -net burn + equity raised (off by ${cash_gap:+.2f}M).")

    ordered = [c for c in ["quarter"] + list(METRIC_INFO) if c in df.columns]
    extra = [c for c in df.columns if c not in ordered]
    return KPIPack(df=df[ordered + extra], issues=issues, source=source)


TREND_METRICS = ["arr_m", "net_new_arr_m", "revenue_m", "nrr_pct", "grr_pct",
                 "gross_margin_pct", "net_burn_m", "burn_multiple", "cash_m",
                 "runway_months", "pipeline_coverage_x", "cac_payback_months",
                 "headcount", "enterprise_logos"]


def streak(series: pd.Series) -> int:
    """Consecutive latest quarter-over-quarter moves in one direction.

    +3 = up three quarters in a row, -3 = down three in a row, 0 = flat last quarter.
    A flat quarter ends a streak.
    """
    vals = [float(v) for v in series.dropna()]
    if len(vals) < 2:
        return 0
    direction = (vals[-1] > vals[-2]) - (vals[-1] < vals[-2])
    if direction == 0:
        return 0
    n = 0
    for a, b in zip(reversed(vals[:-1]), reversed(vals[1:])):
        if ((b > a) - (b < a)) != direction:
            break
        n += 1
    return n * direction


def trends(pack: KPIPack) -> pd.DataFrame:
    """Latest quarter vs prior quarter and vs a year earlier, for each metric.

    For % metrics the change is in points; for the rest it is an absolute change
    plus a % change. `streak` counts consecutive quarters moving the same way.
    These are the only "derived" numbers the AI may quote.
    """
    df = pack.df
    rows = []
    for m in TREND_METRICS:
        if m not in df.columns or pd.isna(df[m].iloc[-1]):
            continue
        name, unit = METRIC_INFO[m]
        cur = float(df[m].iloc[-1])
        row = {"metric": m, "name": name, "unit": unit, "current": cur}
        for label, back in (("qoq", 1), ("yoy", 4)):
            if len(df) > back and not pd.isna(df[m].iloc[-1 - back]):
                prev = float(df[m].iloc[-1 - back])
                row[f"{label}_prior"] = prev
                row[f"{label}_change"] = round(cur - prev, 2)
                if unit != "%" and prev:
                    row[f"{label}_change_pct"] = round((cur / prev - 1) * 100, 1)
        row["streak"] = streak(df[m])
        rows.append(row)
    return pd.DataFrame(rows)


def load_budget_vs_actual(src: Union[str, Path, IO, None] = None) -> pd.DataFrame | None:
    """Optional Q3 budget-vs-actual table (sample only for now)."""
    src = SAMPLE_BVA if src is None else src
    try:
        return pd.read_csv(src)
    except Exception:
        return None
