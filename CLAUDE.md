# Boardroom Rehearsal — project spec

Goal: a Streamlit app that helps a CFO prepare for a board meeting. It reads a
quarterly board KPI pack, flags what the board will probe, generates the 10 hardest
likely questions with answer outlines, and shows how peer CFOs handled similar
questions (from a synthetic Braintrust-style thread library).

## Non-negotiable principles
- All KPI math and risk signals are computed in Python. The LLM never calculates.
- Every question cites the signal IDs behind it; every peer insight cites thread IDs.
- Every number in AI output is verified against the computed KPI table.
- Synthetic data only: fictional company Northbeam Analytics; fictional peer CFOs.
  Nothing from Gartner, clients, or real board materials. No real company or person names.
- Must run with NO API key (demo mode with cached outputs for the sample).
- One-line setup: `pip install -r requirements.txt && streamlit run app.py`

## User and tone
User: CFO of a Series B–D company, 1–2 weeks before a board meeting (the VP Finance /
FP&A lead often prepares the pack).
Tone: direct, specific, board-level. No generic questions, no hype.

## Stack
Python 3.11+ (deployed on 3.12; tested on 3.13), Streamlit, pandas, PyYAML,
scikit-learn (TF-IDF), anthropic SDK, python-docx, pytest.
Model ID lives in one place (`engine/llm.py`, overridable by `BR_MODEL` env var).
API key lookup order: `st.secrets["ANTHROPIC_API_KEY"]`, then the environment / `.env`.

## Architecture (data flows top to bottom)
1. Load — sample pack or uploaded CSV, schema-checked (`engine/kpis.py`)
2. Signals (code) — trends vs targets/thresholds from `signals.yaml` → flags with IDs (`engine/signals.py`)
3. Questions (AI call 1, one per persona) — JSON candidates citing signal IDs (`engine/questions.py`)
4. Rank (code) — severity score, dedupe, keep top 10
5. Peer match (code) — TF-IDF top 3 threads per question above a threshold (`engine/peers.py`)
6. Consensus (AI call 2) — agreement/splits citing thread IDs; Braintrust draft when no match
7. Verify (code) — every figure in AI text matched to the allowed-numbers set (`engine/verify.py`)
8. Brief — downloadable .md / .docx (`engine/brief.py`)
9. Stretch: Grill me (AI call 3)

The LLM only ever sees: the KPI table, the flags (with their precomputed values and
deltas), persona text, and thread text. Any number it may quote must already exist
in that input; `verify.py` builds its allowed set from exactly the same payload.

## Repo layout
```
app.py                      Streamlit UI
signals.yaml                risk rules and thresholds (CFO-readable)
engine/kpis.py              load + schema check + derived metrics/deltas
engine/signals.py           rules -> flags
engine/questions.py         persona calls, ranking, dedupe
engine/peers.py             TF-IDF retrieval + consensus/Braintrust calls
engine/verify.py            number checker
engine/llm.py               Claude client, JSON validation + one retry, demo cache
engine/brief.py             board prep brief (.md, .docx)
prompts/                    system_prompt.md, personas.md, questions.md,
                            consensus.md, braintrust.md, grill.md
data/generate_data.py       deterministic generator (no randomness without a fixed seed)
data/northbeam_board_kpis.csv, data/northbeam_budget_vs_actual.csv, data/peer_threads.json
demo_cache/                 cached AI outputs for the sample, keyed by a hash of the input
tests/                      pytest
```

## Work style
- Propose a plan before big steps; stop at each phase checkpoint for Brandon's review.
- Write tests for math, signals and verify. Commit after each working step.
- Summarize each change in 2–3 bullets.
- Log decisions, corrections and surprises in `BUILD_LOG.md` as they happen.
- After 2 failed attempts at a bug: write a failing test that shows it, then fix only that.
- Never ask for passwords. Never commit `.env`, `.streamlit/secrets.toml`, or keys.
