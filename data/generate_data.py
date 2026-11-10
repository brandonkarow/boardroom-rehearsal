"""Generate the fictional Northbeam Analytics board pack (synthetic data only).

Northbeam Analytics is a fictional Series C B2B SaaS company. Nothing here comes
from a real company, client or board deck.

Design: only the *raw* inputs are typed in below (net new ARR, net burn, the raise,
margins, pipeline, logos, ...). Everything derived — ARR, cash, burn multiple,
runway, revenue — is computed from them, so the pack reconciles by construction:

    ARR_t        = ARR_{t-1} + net_new_ARR_t
    cash_t       = cash_{t-1} - net_burn_t + equity_raised_t
    burn_multiple = net_burn_t / net_new_ARR_t
    runway_months = cash_t / (net_burn_t / 3)

Run:  python data/generate_data.py
Writes data/northbeam_board_kpis.csv and data/northbeam_budget_vs_actual.csv.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent

QUARTERS = ["Q4 2024", "Q1 2025", "Q2 2025", "Q3 2025",
            "Q4 2025", "Q1 2026", "Q2 2026", "Q3 2026"]

# ---- Raw inputs (one value per quarter, oldest first) -----------------------
ARR_END_Q3_2026_M = 48.0          # anchor: ~$48M ARR at the board meeting
CASH_END_Q1_2026_M = 46.2         # anchor chosen so runway is 22.0 months in Q1 2026
SERIES_C_QUARTER = "Q1 2025"      # Series C closes here
SERIES_C_AMOUNT_M = 50.0

RAW = {
    # Net new ARR slows from $4.6M to $2.87M a quarter: the root of most stories.
    "net_new_arr_m":       [4.60, 4.40, 4.50, 4.20, 4.00, 3.60, 3.10, 2.87],
    # Operating plan for net new ARR. Beat or near-miss through Q1 2026,
    # then two material misses (Q2: -20.5%, Q3: -24.5%) -> forecast-credibility story.
    "net_new_arr_plan_m":  [4.40, 4.20, 4.40, 4.30, 4.00, 3.70, 3.90, 3.80],
    # Net burn stays roughly flat at ~$6M a quarter; efficiency collapses because
    # growth slows, not because spend jumps.
    "net_burn_m":          [6.00, 6.00, 6.30, 6.30, 6.40, 6.30, 6.00, 6.03],
    # NRR: 118% -> 109% over the last two quarters (mid-market expansion slowing).
    "nrr_pct":             [120.0, 120.0, 119.0, 119.0, 118.0, 118.0, 113.0, 109.0],
    # GRR holds steady: churn is NOT the problem (the trap: blaming the market).
    "grr_pct":             [92.0, 92.0, 93.0, 92.0, 92.0, 92.0, 92.0, 91.0],
    # Gross margin -3.0 pts YoY after the Q1 2026 data-platform migration (hosting).
    "gross_margin_pct":    [76.2, 76.0, 76.1, 75.8, 75.8, 74.6, 73.5, 72.8],
    # Next-quarter pipeline coverage vs a 3.0x target.
    "pipeline_coverage_x": [3.3, 3.2, 3.4, 3.1, 3.0, 2.8, 2.6, 2.4],
    "pipeline_target_x":   [3.0] * 8,
    # CAC payback drifts up but stays under the 24-month alert line (no flag).
    "cac_payback_months":  [17, 17, 18, 18, 19, 20, 21, 22],
    "headcount":           [210, 228, 246, 262, 275, 286, 294, 298],
    # Enterprise logos: 30 -> 42 YoY (+40%), the positive story.
    "enterprise_logos":    [24, 26, 28, 30, 33, 36, 39, 42],
}


def build_kpis() -> pd.DataFrame:
    df = pd.DataFrame({"quarter": QUARTERS, **RAW})
    n = len(df)

    # ARR roll-forward, anchored on the latest quarter.
    arr = [0.0] * n
    arr[-1] = ARR_END_Q3_2026_M
    for i in range(n - 2, -1, -1):
        arr[i] = arr[i + 1] - df.loc[i + 1, "net_new_arr_m"]
    df["arr_m"] = [round(a, 2) for a in arr]

    # Cash roll-forward, anchored on Q1 2026, with the Series C in Q1 2025.
    raised = [SERIES_C_AMOUNT_M if q == SERIES_C_QUARTER else 0.0 for q in QUARTERS]
    df["equity_raised_m"] = raised
    anchor = QUARTERS.index("Q1 2026")
    cash = [0.0] * n
    cash[anchor] = CASH_END_Q1_2026_M
    for i in range(anchor + 1, n):
        cash[i] = cash[i - 1] - df.loc[i, "net_burn_m"] + raised[i]
    for i in range(anchor - 1, -1, -1):
        cash[i] = cash[i + 1] + df.loc[i + 1, "net_burn_m"] - raised[i + 1]
    df["cash_m"] = [round(c, 2) for c in cash]

    # Derived efficiency metrics (the same formulas engine/kpis.py re-checks).
    df["burn_multiple"] = (df["net_burn_m"] / df["net_new_arr_m"]).round(2)
    df["runway_months"] = (df["cash_m"] / (df["net_burn_m"] / 3)).round(1)

    # Quarterly recognized revenue ~ average ARR in the quarter / 4.
    prev_arr = [arr[0] - df.loc[0, "net_new_arr_m"]] + arr[:-1]
    df["revenue_m"] = [round((a + p) / 2 / 4, 2) for a, p in zip(arr, prev_arr)]

    cols = ["quarter", "arr_m", "net_new_arr_m", "net_new_arr_plan_m", "revenue_m",
            "nrr_pct", "grr_pct", "gross_margin_pct", "net_burn_m", "burn_multiple",
            "equity_raised_m", "cash_m", "runway_months", "pipeline_coverage_x",
            "pipeline_target_x", "cac_payback_months", "headcount", "enterprise_logos"]
    return df[cols]


def build_budget_vs_actual(kpis: pd.DataFrame) -> pd.DataFrame:
    """Q3 2026 P&L budget vs actual, tied to the KPI pack.

    Actual revenue and COGS come from the KPI table (revenue x (1 - gross margin)),
    and 'other cash items' bridges operating loss to net burn, so the P&L and the
    cash view reconcile.
    """
    q3 = kpis.iloc[-1]
    rev_a = float(q3["revenue_m"])
    cogs_a = round(rev_a * (1 - q3["gross_margin_pct"] / 100), 2)
    rev_b, gm_b = 12.00, 76.0
    cogs_b = round(rev_b * (1 - gm_b / 100), 2)

    # Opex lands on budget in total: the Q3 miss is revenue and hosting, not spend.
    opex_b = {"Sales & marketing": 7.10, "Research & development": 4.90,
              "General & administrative": 2.10}
    opex_a = {"Sales & marketing": 7.00, "Research & development": 4.90,
              "General & administrative": 2.20}

    rows = [("Revenue", rev_b, rev_a),
            ("Cost of revenue (incl. cloud hosting)", cogs_b, cogs_a),
            ("Gross profit", round(rev_b - cogs_b, 2), round(rev_a - cogs_a, 2))]
    rows += [(k, opex_b[k], opex_a[k]) for k in opex_b]
    tot_b, tot_a = round(sum(opex_b.values()), 2), round(sum(opex_a.values()), 2)
    rows.append(("Total operating expenses", tot_b, tot_a))
    op_b = round(rev_b - cogs_b - tot_b, 2)
    op_a = round(rev_a - cogs_a - tot_a, 2)
    rows.append(("Operating income", op_b, op_a))
    # Capex + working capital, so that -operating income + other = net burn.
    other_a = round(float(q3["net_burn_m"]) + op_a, 2)
    other_b = 0.40
    rows.append(("Other cash items (capex, working capital)", other_b, other_a))
    rows.append(("Net burn", round(-op_b + other_b, 2), round(-op_a + other_a, 2)))

    df = pd.DataFrame(rows, columns=["line_item", "budget_m", "actual_m"])
    df["variance_m"] = (df["actual_m"] - df["budget_m"]).round(2)
    df["variance_pct"] = (df["variance_m"] / df["budget_m"].abs() * 100).round(1)
    df.insert(0, "quarter", "Q3 2026")
    return df


def main() -> None:
    kpis = build_kpis()
    bva = build_budget_vs_actual(kpis)
    kpis.to_csv(DATA_DIR / "northbeam_board_kpis.csv", index=False)
    bva.to_csv(DATA_DIR / "northbeam_budget_vs_actual.csv", index=False)
    print(kpis.to_string(index=False))
    print()
    print(bva.to_string(index=False))


if __name__ == "__main__":
    main()
