# Build log — Boardroom Rehearsal

Running record of decisions, corrections and surprises. Times are America/New_York.

## 2026-11-10 — Phase 1: setup

- **Setup:** the agent builds in its own cloud workspace (Python 3.13 there; the code
  targets 3.11+ and Streamlit Cloud will run 3.11). Code reaches GitHub at Phase 4.
- **Decision:** wrote CLAUDE.md from the plan's Step 0 spec, plus the architecture,
  repo layout and work-style rules, so every later step can be checked against it.
- **Spec gaps raised before building** (see the file-plan proposal in chat):
  forecast-miss data for the Independent Director persona, which numbers the
  verifier may accept, the time base for "enterprise logos +40%", and where the
  demo cache comes from without a key in this workspace.
- **Agreed (Brandon: OK):** add net-new-ARR plan for all quarters (forecast-miss
  signal), derive runway in code, verifier accepts only KPI-table + precomputed
  flag numbers, logos +40% is YoY, 5 candidates per persona.

## 2026-11-10 — Phase 2: data and risk signals

- **Surprise:** the build workspace's network policy blocks installing `streamlit`
  and `anthropic` (403 from the egress proxy). pandas, scikit-learn, PyYAML and
  pytest were already there, so the engine is fully testable here. The UI's first
  real run will be on Streamlit Cloud (or Brandon's Mac). Kept the LLM layer
  thin so it can be tested with a fake client.
- **Decision: generator types only raw inputs** (net new ARR, net burn, the raise,
  margins…); ARR, cash, burn multiple, runway and revenue are derived, so the pack
  reconciles by construction. Tests re-check every identity.
- **Decision: the Series C ($50M) closes in Q1 2025.** Without it, runway can't
  fall 22 → 17 months while cash and burn tie out. Runway is 35.8 months after the
  raise, 22.0 in Q1 2026, 17.0 in Q3 2026. Net burn stays ~$6M a quarter: the
  efficiency story is slowing growth, not rising spend.
- **Decision: budget vs actual ties to the KPI pack.** Revenue and COGS come from
  the KPI table; an "other cash items" line bridges operating loss to net burn.
  Opex lands on budget in total, so the Q3 miss is revenue (-3.0%) and hosting
  (cost of revenue +10.1%), which matches the gross-margin story.
- **Correction (own):** first pass flagged all six concerns red, which reads as
  cartoonish and gives ranking nothing to work with. Recalibrated to common board
  thresholds: gross margin amber at -2 pts YoY (red at -4), runway amber under 18
  months (red under 12). Result: 4 red, 2 amber, 1 positive.
- **Decision: two watch-list rules (GRR < 90%, CAC payback > 24 months) that must
  NOT fire** on the sample. A test proves the rules discriminate rather than flag
  everything. GRR held at 91–93%, which sets up the "don't blame churn" trap.
- **Bug caught by a test:** level rules (burn multiple, runway) were skipped on a
  short history because their optional year-ago comparison was treated as
  required. Fixed: they now fire on the level alone with a simpler sentence.
- 23 tests pass. Commit `3a7a6a0`.

## 2026-11-10 — Phase 3: personas, the hard 10 and the verifier

- **Decision: model `claude-sonnet-5-5`** (latest Sonnet per the Anthropic models
  page, checked today), overridable with `BR_MODEL`. One place in `engine/llm.py`.
- **Decision: demo cache keyed by task + a hash of the input data**, not the prompt
  wording, so tuning prompts doesn't silently break demo mode. Live runs record
  every validated output; the sidebar offers "Download demo cache" so the cache can
  be committed without a key ever entering the chat.
- **Deviation from the plan's personas.md (for Brandon to confirm):** the Growth VC's
  signature line "get NRR back above 115%" names a target that isn't in the data,
  so under the verifier it would fail. Changed to "back to 118%" (the Q1 2026 level).
- **Added TRENDS and THRESHOLDS to the prompt.** Board questions naturally use
  QoQ/YoY changes and alert lines ("below 18 months"). Giving the model those
  code-computed numbers is the only way to let it say them without calculating.
- **Correction (caught by tests): the first verifier matched figures by value
  alone,** so "runway 18 months" passed (18 is a threshold) and "Runway is 19
  months" passed (19 was CAC payback in Q4 2025). Rebuilt it to be metric-aware:
  each figure is matched only against computed numbers for the metric the sentence
  names (nearest mention before it first), and thresholds count only when the text
  calls them one ("below the 18-month line"). Second fix: "$12M budget ... while
  opex" was matched to opex; now mentions *before* a figure win.
- **Decision: questions with an unverified figure are held back, not shown.** They
  appear in a "Held back by the verifier" expander with the bad figure and why, so
  the top 10 is always green and nothing is hidden.
- **Correction (own, from reading the fixture ranking):** scoring by the most
  severe cited signal let a thin positive-story question jump to #4 because it also
  tagged BURN_MULTIPLE. Now: score = the *primary* (first-cited) signal's severity
  + 0.1 per linked signal; at most 2 questions led by the same signal; coverage
  prefers questions led by the flag. Prompt now asks for the main signal first.
- **Testing without Streamlit or the SDK:** a FakeClient serves a hand-written
  fixture (clearly labeled, not model output, not used by the app), including an
  uncited question, a duplicate, and an invented "125%" NRR target. A smoke test
  runs app.py top to bottom against a stand-in for Streamlit. 64 tests pass.
- **Open:** real question quality can only be judged on live model output (Phase 4).

## 2026-11-10 — Phase 4: first deploy

- **Decision: pins checked on PyPI today.** streamlit 1.66.1 (not the 5-day-old
  1.67.0), anthropic 2.3.0, pandas 3.0.5, scikit-learn 1.9.1. numpy left unpinned:
  numpy 2.5 needs Python 3.12, so pinning it would break the one-line setup on 3.11.
  Deploy target: Python 3.12.
- **Surprise: GitHub was connected but the session couldn't push.** This workspace
  only gets push credentials for repos attached when the session starts, and the
  repo was created afterwards. Brandon chose to upload a zip through GitHub's web
  uploader at each checkpoint, which keeps the whole build in one chat history.
  The commit history in GitHub will be per-checkpoint uploads; the step-by-step
  history lives in this log and the chat.
- **Correction (own):** dropped `.streamlit/config.toml` (a theme only). macOS hides
  dot-folders, so it wouldn't survive a drag-and-drop upload. `.gitignore` gets
  created in GitHub's web editor instead.
- **API key setup:** the key goes in a dedicated Console workspace with its own
  monthly spend limit (the default workspace can't have one), and only into
  Streamlit's Secrets box, never into this chat.
