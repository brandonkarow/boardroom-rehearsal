TASK
You are playing one board member, described in PERSONA. The board meeting reviews
{quarter}. Write the {n} hardest questions this board member is likely to ask the
CFO, based only on the data below.

For each question:
- Cite 1–3 signal_ids from SIGNALS that the question is about, the main one first.
  Use the ids exactly.
- Ask it in the board member's voice: specific, naming a number and a cause or decision.
- why_they_ask: one sentence on what this board member is really worried about.
- answer_outline: exactly 3 short bullets the CFO can say in 60 seconds:
  1) the headline, 2) the evidence (numbers from the data), 3) the action or decision.
- trap_to_avoid: one sentence on the answer that would hurt the CFO's credibility
  (e.g. blaming the market when the data points elsewhere).
Cover different signals; don't ask the same thing twice. If SIGNALS has a positive
signal that fits this persona, include one question that lets the CFO tell that story.
Numbers: use only figures that appear in the data below. Do not compute new ones.

PERSONA
{persona}

SIGNALS (computed in code)
{signals}

TRENDS (computed in code; latest quarter vs prior quarter and vs a year earlier)
{trends}

THRESHOLDS (the board's reference points)
{thresholds}

KPI_TABLE (last {n_quarters} quarters)
{kpi_table}

BUDGET_VS_ACTUAL ({quarter})
{bva}

OUTPUT
Return only JSON, in this shape:
{{"questions": [{{"question": "...", "signal_ids": ["..."], "why_they_ask": "...",
"answer_outline": ["...", "...", "..."], "trap_to_avoid": "..."}}]}}
