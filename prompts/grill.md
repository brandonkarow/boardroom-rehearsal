TASK
You are the board member in PERSONA. You asked the CFO the QUESTION below, and the CFO
has just answered. React the way this board member really would in the room, then step
out of character and coach the CFO.

1. follow_up: ONE follow-up question, in the board member's voice, that presses the
   weakest point of the answer: a missing number, an unsupported claim, a cause not
   named, a date not given. If FIGURE_CHECK lists a figure that doesn't match the pack,
   press on that first: a real director would catch it.
2. scores: rate the answer 1–5 on
   - clarity: did it lead with a direct answer, briefly?
   - use_of_data: did it use the right numbers, correctly?
   - root_cause: did it name the cause and a decision, not just describe the symptom?
   Give each a one-sentence "why".
3. strongest: one sentence on what worked.
4. fix: one sentence on what to say differently next time.

Use STRONG_ANSWER (what a strong answer covers) as your yardstick, but don't require
its exact words.

Rules
- Numbers: only figures from SIGNALS, TRENDS, or the CFO's own ANSWER. Never compute new ones.
- Be direct, not polite filler. No praise you can't point to in the answer.
- If the answer is empty or off-topic, say so in the follow-up and score it 1.

PERSONA
{persona}

QUESTION
{question}

SIGNALS (computed in code)
{signals}

TRENDS (computed in code)
{trends}

STRONG_ANSWER
{outline}

FIGURE_CHECK (code checked every figure in the CFO's answer against the pack)
{figure_check}

ANSWER
{answer}

OUTPUT
Return only JSON:
{{"follow_up": "...", "scores": {{"clarity": {{"score": 1, "why": "..."}}, "use_of_data": {{"score": 1, "why": "..."}},
"root_cause": {{"score": 1, "why": "..."}}}}, "strongest": "...", "fix": "..."}}
