# Boardroom Rehearsal

Walk into the board meeting having already heard the 10 hardest questions, with answer
outlines grounded in your numbers and how peer CFOs handled the same questions.

**Live app:** https://boardroom-rehearsal.streamlit.app
**Try it in 60 seconds:** click **Load Northbeam Q3 board pack** → **Rehearse** → open a
question card → scroll to **How peers handled it** → **Download brief (.docx)**.

**Run locally:**
```
pip install -r requirements.txt && streamlit run app.py
```
Runs with no API key, in demo mode. Python 3.11+. To run the AI live, put
`ANTHROPIC_API_KEY=sk-ant-...` in a `.env` file (or in Streamlit secrets) and choose
**Live AI run** in the sidebar.

All data is synthetic. Northbeam Analytics is a fictional Series C SaaS company, and every
peer CFO thread is fictional. Nothing comes from a real company, board deck or community.

---

## The problem

The question that hurts a CFO in a board meeting is rarely the one they prepared for. It's
the second question, the follow-up from the independent director who noticed that the
plan barely moved after last quarter's miss.

I spent years at Gartner working on the Conferences business and on integrating Evanta,
Gartner's C-level communities, including the meeting and peer-connect capabilities. The
pattern I saw over and over: the most valuable thing an executive gets from a community
isn't content. It's the moment a peer says, "I had that exact problem two years ago. Here's
what I said, and here's what I'd do differently." That moment is worth the most the week
before a board meeting, and it's the hardest to get. You can't call twelve CFOs at 11pm
to ask how they explained a falling NRR.

Board prep today is a deck, a few dry runs with the CEO, and the CFO's memory of what this
board tends to ask. Boardroom Rehearsal does three things that I think CFOs actually want
that week. It reads the numbers the way a skeptical board will. It asks the hard questions
before the board does. And it puts what peers did next to each question. Because a CFO
can't afford to quote a wrong number in that room, every figure is computed in code and
checked, and every peer insight is traceable to the thread it came from.

## What it does

1. **Flags what the board will probe (code).** Reads the quarterly KPI pack, recomputes
   the derived metrics, checks the roll-forwards, and applies CFO-readable rules in
   [`signals.yaml`](signals.yaml). Northbeam gets 4 red, 2 amber and 1 positive signal.
2. **Asks the hardest questions (AI, then code).** Three board personas (Growth VC,
   Skeptical Independent Director, Cash-Focused Lead Investor) each propose 5 questions
   citing the signals behind them. Code ranks them by signal severity, drops
   near-duplicates, makes sure every signal is covered, and keeps the top 10. Each card
   shows why they'll ask, the data behind it, a 3-line answer outline and the trap to avoid.
3. **Checks every number (code).** Every figure in the AI's text is matched against the
   computed numbers *for the metric that sentence is about*. A question with a figure that
   doesn't match is held back and shown with the reason.
4. **Shows how peers handled it (code, then AI).** TF-IDF retrieval finds 2–3 peer threads
   per question from a library of 40. Code counts which approaches peers took. The AI
   writes the summary and cites thread IDs, and code attaches the counts.
5. **Drafts a Braintrust question where peers haven't covered it.** It's anonymous by
   construction: code turns the company's numbers into ranges, and a draft that names the
   company or uses an exact figure is rejected.
6. **Hands you a brief.** Two pages to take into the room, plus an appendix.

## Design principles, and how each is enforced

| Principle | Enforced by |
|---|---|
| The AI never calculates | KPI math, trends, streaks ("down three quarters in a row") and peer counts are all computed in code and passed in. |
| Every number is verified | [`engine/verify.py`](engine/verify.py) links each figure to the metric it's about. Thresholds only count when the text names them ("below the 18-month line"). Claims about runs of quarters are checked against code streaks. |
| Every question cites its signals | Questions without a valid signal ID are dropped before ranking. |
| Every peer insight cites its threads | Points citing a thread that wasn't retrieved are dropped. The AI may not write counts: it names an approach and code writes "3 of 10 replies". |
| Anonymous escalation | Braintrust drafts may only use code-made ranges ("$25–50M ARR", "105–110% NRR"). |
| It runs for anyone | Demo mode replays a saved live run and re-runs every check on it. No key needed. |

## How it was built

Built in one session with Claude as the coding agent, spec first
([`CLAUDE.md`](CLAUDE.md)), in phases with a review checkpoint after each. Decisions,
corrections and surprises are logged in [`BUILD_LOG.md`](BUILD_LOG.md). The full agent
chat history is submitted alongside. A few moments worth reading in the log:

- **The verifier was rebuilt three times on real model output.** The first version matched
  figures by value alone, so "runway 18 months" passed because 18 is a threshold.
- **A card with all-true numbers made a false claim**, "margin has fallen four quarters in
  a row" (it was three). That led to code-computed streaks.
- **Peer counts moved from the AI to code** after the first live run showed a count could
  be attached to the wrong approach.
- **Retrieval calibration found a flaw:** an unrelated "data privacy" question matched a
  margin thread, so matching was reworked into topic plus question wording, with an
  honest coverage grade.

**Tests:** `pytest` runs 125 tests, including attacks on each guardrail, messy Excel exports,
and a regression suite on real model output.

## Out of scope, and what I'd build next

- Reading real board decks (PDF or slides); this prototype reads a KPI CSV.
- A real Braintrust integration; the threads are synthetic and "Post" is a mock.
- Accounts, saved history, and more than one company.
- Next: "Grill me" practice mode (answer a question; the board member pushes back once),
  board-member profiles ("this investor always asks about cohorts"), and prep notes that
  carry from one quarter to the next.

## Path to Floyd

What I learned building peer-connect at Evanta is that communities don't win on the
number of conversations. They win when a member gets the right peer at the right moment.
Board prep is a moment that comes back every quarter for every CFO. That makes it a
natural habit for Floyd, and a natural way into the Braintrust.

**The loop:** a member uploads the board pack → Floyd flags what the board will probe and
the likely questions → Floyd shows how peers handled each one (real threads, with consent)
→ questions peers haven't covered go to the Braintrust as anonymous drafts → those answers
improve the next member's prep. Every board cycle makes the library better, and no
competitor without a peer community can copy that.

| | |
|---|---|
| **Who it's for** | CFOs first. Then the FP&A leads and Deputy CFOs who actually build the pack, as team seats; that's how The F Suite grows into the finance team. |
| **Positioning** | "Walk into every board meeting having already heard the hard questions, and how your peers answered them." |
| **How I'd launch it** | 10–15 design-partner CFOs for one board cycle, then an anonymized "most-asked board questions this quarter" report, then showcase it at chapter dinners and the summit before general release. Starting small also tests the hardest part first: whether members will let their threads inform other members' prep. |
| **The flywheel** | Every uncovered question becomes a Braintrust thread, and every answered thread improves the next member's prep. A quarterly "top board questions by stage" report becomes a benchmark asset in its own right. |
| **Trust** | Member financials never train models. Threads appear in summaries only with opt-in. Escalations are anonymous by default, and retention is clear. In a CFO community, a privacy mistake would cost more than any feature is worth. |
| **What I'd measure** | Share of members using it before board meetings; Braintrust questions started from it and their response rate; prep time saved (self-reported); and renewal rates of users vs non-users. That last one is the number that matters. |

## Repo map

```
app.py                    Streamlit UI
signals.yaml              risk rules, thresholds and peer search words (CFO-readable)
engine/kpis.py            load, schema checks, derived metrics, trends and streaks
engine/signals.py         rules → flags
engine/questions.py       persona calls, ranking, dedupe
engine/verify.py          the number checker
engine/peers.py           retrieval, approach counts, consensus and Braintrust drafts
engine/llm.py             Claude client, JSON validation and retry, demo cache
engine/brief.py           board prep brief (.docx, .md)
prompts/                  system prompt, personas, task prompts
data/                     synthetic board pack, budget vs actual, 40 peer threads
demo_cache/cache.json     one saved live run (7 AI outputs) for demo mode
tests/                    pytest
```
