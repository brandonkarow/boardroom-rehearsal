TASK
For each board question below, summarize how peer CFOs in the matched Braintrust
threads handled the same issue. The CFO will read this right before the meeting.

Inputs per question (all computed or retrieved by code):
- question: the board member's question.
- threads: the peer threads code retrieved, with every reply's stage, industry,
  approach tag and whether the reply pushed back on the others.
- approach_counts: how many replies took each approach, counted by code
  ("replies" out of "of"), with the threads each approach appears in.

Write for each question:
- headline: one sentence, the single most useful thing peers did.
- points: 2–3 points. Each says what peers did and why, cites the thread_ids it
  comes from, and may give a count ONLY as it appears in approach_counts
  (e.g. "4 of 11 replies ..."). Prefer specifics from the replies over generalities.
- split: if any reply pushed back, one sentence on the disagreement and the reason
  given, with its thread_ids. Otherwise null.
- stage_note: one sentence if the advice depends on stage or industry, else null.

Rules
- Only cite thread_ids that appear in that question's threads.
- Numbers: only counts from approach_counts, or figures quoted in the replies.
  Never compute a percentage or total yourself.
- Don't invent consensus: if replies disagree, say so. Don't mention the company's
  own figures; these are peers' experiences.
- Write about peers in the third person ("peers", "one Series D CFO"). No names.

INPUT
{payload}

OUTPUT
Return only JSON:
{{"summaries": [{{"q_id": "Q1", "headline": "...", "points": [{{"text": "...", "thread_ids": ["BT-...."]}}],
"split": {{"text": "...", "thread_ids": ["BT-...."]}} or null, "stage_note": "..." or null}}]}}
