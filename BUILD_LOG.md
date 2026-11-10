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
- **Deploy failure 1 (`ModuleNotFoundError: engine`), diagnosed from the log plus a
  read-only clone of the public repo:** dependencies installed fine (Cloud defaulted
  to Python 3.14.10). But the web upload had flattened every file into the repo
  root (`kpis.py`, `__init__ (1).py`, …), so no `engine/` folder existed. Fix: delete
  and recreate the repo, re-upload from an extracted copy, and have the agent
  verify the file tree by cloning before redeploying (with Python 3.12 and secrets
  set this time). Also made the three empty `__init__.py` files non-empty, in case
  the uploader skips zero-byte files.
- **Deployed:** https://boardroom-rehearsal.streamlit.app (Phase 4 core, live mode).

## 2026-11-10 — First live run (agent ran it in the browser pane)

Result: green badge, 95 figures checked, but only **9** questions shown and **4 held
back**. Read every card as a board member would. Found:

- **Verifier false positives (4 held back, including the Loom's signature question**
  "At a 2.1x burn multiple and 17 months of runway, when do you need to raise?"). The
  model referred to thresholds the way people do ("inside the 18-month line",
  "two misses beyond 10%", "the 25% bar"). The checker only recognized a threshold
  when a cue word came *before* it. Fixed: cue words before or after, wider window,
  and a referenced threshold may match any rule's line. "Runway is 18 months" still fails.
- **A false claim with all-true numbers (card #7):** "margin has fallen in each of
  the last four quarters". It fell for three: Q4 2025 was flat at 75.8%. The verifier
  only checked figures, so the claim slipped through. Fixed at the root: counting
  quarters is calculating, so code now computes a `streak` per metric (shown to the
  model in TRENDS), and the verifier checks "N straight/consecutive quarters",
  "N quarters in a row/running" and "each of the last N quarters" against it.
  A test caught my own wrong expectation too: pipeline coverage has fallen *five*
  quarters running, not four.
- **Persona bleed:** the Growth VC asked the forecast-credibility question, the
  Independent Director asked the burn/cut and enterprise questions. Fixed: the prompt
  tells each persona to stay in its lane (at most one question outside it), and
  ranking gives +0.2 when the persona asking is the one signals.yaml assigns.
- **Two near-identical enterprise questions** (#8 and #9) both made the cut. Fixed:
  at most one question led by a positive signal.
- **"$" broke rendering:** Streamlit reads `$…$` as a LaTeX formula, so
  "$0.29M over budget … ($8.47M" rendered as italic math. Fixed: dollar signs are
  escaped in every markdown line.
- **Speed: about 3.5 minutes** for the three persona calls, run one after another
  with Sonnet 5.5's adaptive thinking. Too slow for a reviewer. Fixed: the three
  personas now run in parallel (cache writes are locked).
- **Held-back cards now show the sentence that failed**, so a reviewer can see why.
- What was good: every figure checked out against the data; the answer outlines say
  plainly what the data can't show ("the data here does not split expansion by
  product, price or segment"); traps are specific (e.g. "don't blame the market when
  GRR held").
- 74 tests pass.

## 2026-11-10 — Second live run (after fixes)

- **58 seconds** end to end (was about 3.5 minutes): the parallel persona calls work.
  Green badge, 95 figures checked, 1 held back. The signature question is now #1. Streak
  claims were checked live ("fallen five quarters in a row" ✓, "three quarters in a
  row" ✓); the four-vs-three margin error didn't recur.
- **The verifier caught real AI arithmetic:** "the Q3 plan … was only $0.1M lower".
  True (3.9 → 3.8), but the model subtracted to get it, which the rules forbid. Held
  back correctly. Because plan-over-plan change is a fact a director would raise,
  code now computes it: `net_new_arr_plan_m` is added to TRENDS. Any other amount
  ("$0.4M lower") still fails.
- **Still 9, not 10:** the strict caps (4 per persona, 2 per signal, 1 positive) ran out
  of eligible candidates. Added a third pass that relaxes the caps, never the dedupe,
  so the list fills to 10.
- **Leak of internal labels:** card #9 said "The streak is seven quarters of growth,
  from TRENDS." Prompt now bans input labels in CFO-facing text.
- Persona lanes improved (the Director now asks forecast/pipeline and margin), though the
  Growth VC still took one burn question. Left it: it's framed as a growth investor's
  question ("is the burn still buying growth?").
- 76 tests pass.

## 2026-11-10 — Third live run: crash

- **Crash:** `engine.llm.LLMError` reached the user as a red error page. Two bugs:
  1. **Stale cached client.** `@st.cache_resource` kept the LLM object built by the
     *previous* code version alive across the redeploy. Its exception class came from
     the old module, so the new code's `except LLMError` didn't match it (the traceback
     mixed old and new line numbers). Fix: build the client fresh each run, and catch
     any exception per persona so one board member's failure never takes the app down.
  2. **Probable cause of the failure itself:** max_tokens was 4,000, but Sonnet 5.5's
     adaptive thinking counts toward it, so a detailed reply can be cut off mid-JSON
     (twice → "invalid output"). Fix: 16,000 tokens, and a cut-off reply (stop_reason
     `max_tokens`) is reported as exactly that, so the cause is visible in-app next time.
- 78 tests pass.

## 2026-11-10 — Fourth live run: clean (Phase 4 checkpoint met)

- **10 questions, 48 seconds, 113 figures verified, no crash.** The Director's
  forecast question (with the code-computed "$0.1M below the Q2 plan") is now #2;
  "margin has fallen three quarters in a row" is correct and checked.
- **Two more verifier false positives,** both from how the checker links a figure to
  its metric: "the 40% logo growth" (only the plural "logos" was a keyword) and "a
  9-point drop in retention" (the hyphenated "9-point" lost its unit, and bare
  "retention" wasn't a keyword, so it was matched to "revenue"). Fixed, with the exact
  live sentences as regression tests. "A 7-point drop in retention" still fails.
- Pattern so far: four rounds of live output found false positives (rejecting true
  figures). None found a false negative (accepting a wrong one). Over-strict is the
  right failure mode for a CFO tool; each new phrasing becomes a test.
- 82 tests pass.

## 2026-11-10 — Demo cache attempt: caught a mixed export

- **Brandon downloaded the cache; on inspection it mixed two runs.** Cash Investor and
  Director entries came from the clean run (14:52), but Growth VC came from the crashed
  run (14:48), and that entry still carried the "from TRENDS" leak. Cause: the sidebar
  button exported whatever was on disk when the page rendered. Not committed as the
  demo cache. Fix: every cache entry is tagged with the run that produced it, and a
  "Save this run as the demo cache" button below the results exports exactly that run.
  The coherent cache will be saved in Phase 6, once the peer layer adds its own AI calls.
- **Used it as real-model test data instead** (tests/fixtures/live_cache_2026-11-10.json,
  hand-checked: every figure is correct). It exposed one more verifier false positive:
  in "…(-20.5%) and Q3 … (-24.5%); coverage is 2.4x", the -20.5% was linked to
  "coverage" in the next clause. Fix: semicolons end a clause, and a metric named
  *after* a figure only counts when it is right next to it ("40% logo growth").
  New regression test: the real output must verify 100% and rank a full, covering top 10.
- 85 tests pass.

## 2026-11-10 — Phase 5: peer-consensus layer

- **Design decision (Brandon: "the most valuable part, knock it out of the park"):**
  "4 of 5 CFOs led with cohort data" is a number, so the AI may not produce it. Every
  reply in the library carries an `approach` tag; code counts approaches across the
  retrieved threads and hands the AI the tallies. The AI writes sentences and cites
  thread IDs. Code drops any point that cites a thread it didn't retrieve or uses a
  number that is neither a code count nor a figure quoted in those threads.
- **Braintrust drafts follow the same rule:** code turns the company's numbers into
  ranges ("$25–50M ARR", "105–110% NRR", "12–18 months of runway"). A draft that names
  the company or contains any other figure is rejected and retried.
- **Library: 40 synthetic threads, 136 replies, 63 labeled approaches.** 29 threads
  include at least one pushback reply with a stated reason (stage, risk, a reversal
  that went wrong). Stages from Series B to pre-IPO; 10 industries including
  marketplace and fintech. Four deliberately off-topic threads (auditor switch, ASC 606,
  planning tools, equity refresh) stand in for real community traffic and test that
  retrieval ignores them. Screened every capitalized word: no real companies or people.
  Correction (own): the first draft had no marketplace CFOs, which the plan asked for.
- **Retrieval tuning, in four steps, on the 15 real questions from the live cache:**
  1. Plain TF-IDF over question + all cited signals' keywords: right top thread, but a
     secondary signal ("…and margin") pulled in the wrong topic.
  2. Main signal's keywords only, plus a 60% relative floor: precise but too thin
     (forecast questions got one thread).
  3. Calibration test exposed a real flaw: an unrelated "data privacy" question scored
     0.46 because signal keywords dominated, so matching was a topic lookup, not
     reading the question. The question's own words were too short to be a hard gate.
  4. Final: topic boost for the main signal's `peer_topic` (in signals.yaml), the
     question's own wording blended into the ranking (weight 0.5), floors for the 2nd
     and 3rd thread, and a **coverage grade**: "close" when the question's own words
     match a thread, "topic" when peers discussed the area but not this exact question.
     Topic-only questions get peer insights **and** a Braintrust draft.
  Result on the live questions: 11 close, 4 topic-only (three enterprise-quality
  questions, plus "how much of the burn multiple is NRR"). Off-topic threads are never
  retrieved. Stopped tuning there to avoid overfitting 15 questions.
- **Speed:** consensus runs in batches of 4 questions, in parallel with the drafts, as a
  second visible step ("Finding how peer CFOs handled each one…").
- 101 tests pass, including attacks on every guardrail: a citation to a non-retrieved
  thread, an invented "7 of 9 CFOs", and drafts containing "Northbeam", "109%" or "$48M".

## 2026-11-10 — First live run of the peer layer (agent read every summary)

- **92 seconds end to end** (about 45s questions + 45s peers). 10 of 10 cards got peer
  insights, 124 figures verified. Spot-checked the summaries against the threads, and
  they're faithful ("3 of 10 replies judged pipeline on stage-by-stage conversion" =
  BT-1031 ×2 + BT-1034; "Series B CFO removed 20% of pipeline"; "about $400K a year in
  overlapping software"). They report disagreement and say when evidence is thin.
- **Most important finding: count attribution.** The AI wrote "N of M replies …"
  itself. The check only confirmed N and M were real tallies, not that they belonged
  to *that* approach. Fix: the AI names an approach tag; **code writes the count and
  label** next to the AI's sentence, and adds every thread with that approach to the
  citation. Any count the AI writes ("3 of 10", "two of the twelve") is dropped, even a
  true one. Each card shows how many AI points the checks dropped.
- **A key point silently dropped:** on the raise-timing card, the main thread's advice
  ("start with 18+ months") was removed because 18 appears only in the approach label.
  Fix: label figures are allowed.
- **No Braintrust drafts appeared:** the enterprise card had one thread and three
  replies but scored "close" on wording. Fix: fewer than two threads is thin coverage
  and gets a draft.
- **Verifier false positive:** "a 9-point drop" in a trap sentence that names only GRR
  (the card is about NRR). Fix: a point change may match a code-computed change for any
  metric the card names. "GRR held, but there was a 9-point drop" still fails.
- 107 tests pass.

## 2026-11-10 — Peer layer verified live (Phase 5 checkpoint met)

- 101 seconds end to end. 106 figures verified, nothing held back. 9 of 10 cards have close
  peer coverage, and every card shows code-made counts ("2 of 3 replies proved the good
  news was repeatable"). The checks dropped 0 AI points this run.
- The enterprise card (one thread) shows peer insights plus an anonymous Braintrust draft,
  built only from code ranges: "Series C B2B SaaS company at $25–50M ARR. Enterprise
  logos are up 40–50%… missed plan by 20–25% for 2 quarters. How did you test whether
  your enterprise motion was repeatable…?"
- The AI flagged its own limits unprompted: "none of it addresses enterprise buyer,
  sales cycle or expansion mechanics."
- Brandon judged the thread library good enough for now. This run (7 AI outputs:
  3 personas, 3 consensus batches, 1 draft) is the candidate demo cache.

## 2026-11-10 — Phase 6: demo cache, mode switch, brief, polish

- **Demo cache committed** (`demo_cache/cache.json`): Brandon saved the verified live run
  (7 outputs, one run_id). **A test caught a replay bug before it shipped:** the cache
  stores *checked* output, and the peer checks only accepted the AI's raw shape, so all
  four peer batches failed in demo mode with KeyError. Fix: the checks accept their own
  output, so demo mode re-runs every check on the cached run. New test: the committed
  cache must replay the full experience with no key.
- **Decision: a sidebar mode switch, "Instant demo (saved run)" as the default for the
  sample, plus "Live AI run".** With a key in Streamlit Secrets, every reviewer click would
  otherwise cost ~100 seconds and API credit. Demo mode states that it replays a saved live
  run and re-checks it.
- **Brief (.docx and .md). Correction (own): the first version ran 9 pages / 4,600 words**
  against the build guide's "1–2 pages you'd hand a CFO". Restructured: pages 1–2 are
  "the hard 10 at a glance" (question · say · avoid · what peers did); full outlines, peer
  points with code counts and citations, and Braintrust drafts move to an appendix after a
  page break. Checked by rendering the .docx to PDF and looking at the pages.
- **First 60 seconds:** one-line value proposition, a four-step "how it works" line, and a
  "try it in 60 seconds" prompt on the empty state.
- 113 tests pass.

## 2026-11-10 — Phase 7: harden, document, package

- Verified Phase 6 live: instant demo is the default, results arrive 1 second after
  Rehearse, the badge is green, and the brief downloads are present. Brandon parked
  Grill Me until after Phase 7 (agreed cut rule: drop it if the follow-ups are weak or slow).
- **Skeptical-CFO uploads, 15 cases.** Found one crash (pipeline target of 0 →
  ZeroDivisionError) and four rough edges. Fixes: the rule skips with a reason;
  "$48.0M" / "109%" / "1,234" cells parse; semicolon CSVs (European Excel) are
  detected; plausibility warnings for values a CFO would call a data error (NRR 500%, GRR
  over 100%, negative cash, ARR typed in dollars instead of $M); a template CSV download.
  Already fine: Excel BOM, thousands separators, negative net new ARR, cash-flow-positive
  quarter, one quarter only, empty file, .xlsx renamed .csv.
- **Bug found while writing a test:** pandas 3 stores text in its own string type, so the
  "$/%" cleanup never ran on real exports until the type check was fixed.
- **Own pack, no key:** previously three separate "cache miss" warnings. Now the risk
  signals still render (code needs no key), and Rehearse is disabled with one plain
  sentence on what's needed.
- **Test-harness correction:** the fake Streamlit "clicked" disabled buttons, which real
  Streamlit never does; fixed the fake, not the app.
- **README drafted** from the plan's outline, with real mechanisms and numbers. The
  "The problem" and "Path to Floyd" sections are marked for Brandon to rewrite in his voice.
- **Instructions file packaged:** the prompts plus a one-page guide to what each does.
- **Clean-room note:** this workspace can't install Streamlit, so the true one-line
  setup was proven by Streamlit Community Cloud, which does a fresh install from
  requirements.txt on every deploy. Every upload was also checked by a fresh `git clone`
  plus the full test suite.
- 125 tests pass.
- **Phase 7 verified live (10:47 upload):** repo identical to the build, 125 tests pass on
  a fresh clone. Reviewer path on the public URL: "Try it in 60 seconds" prompt and
  template download present. Load → Rehearse gives results in about 1 second, a green
  badge (106 figures), 10 cards, 9 of 10 with close peer coverage, 1 Braintrust draft,
  both brief downloads, and no errors.

## 2026-11-10 — README in Brandon's voice, and Grill me

- **README:** Brandon asked the agent to draft "The problem" and "Path to Floyd" in his
  voice. They draw only on what he has said about himself (Gartner Conferences and
  research; integrating Evanta; building its meeting and peer-connect capabilities). No
  invented facts or metrics.
- **Grill me (Brandon overrode my "skip" recommendation; built after Phase 7 as agreed).**
  The narrow version is one card, the CFO's answer, one follow-up from that board member,
  and 1–5 coaching on clarity, use of data and root cause. The trust twist: **code checks
  every figure in the CFO's own answer first** ("You said 18 months; the pack shows
  runway of 17 months in Q3 2026"). The AI must press on any mismatch. Scores are
  labeled as the AI's judgment, and any figure in its feedback must come from the pack or
  the answer. Demo mode replays one saved exchange on a sample answer that was written for
  the demo, with one deliberate rounding error, the kind CFOs make under pressure.
- **Real verifier hole found while testing it:** "runway is really 11 months" passed,
  because runway *fell* 11 months year over year; the checker accepted a change as a level.
  Fix: computed changes only match figures phrased as changes ("fell 11 months", "a 9-point
  drop", "-9 pts", "added 3"). Re-ran both real-output fixtures. First pass rejected four
  true phrasings ("added 3", "12 net new logos", "40% logo growth"); added those words.
  Real output passes 100% again, and the hole stays closed.
- Test correction (own): an earlier example, "runway is really 14 months", wasn't actually
  invented. Runway was 13.8 months in Q4 2024, so the checker was right to accept it.
- 138 tests pass (1 skipped until the saved Grill me exchange is in the demo cache).
- **Grill me saved for demo mode:** the agent ran one live exchange on the deployed app
  (Instant demo rehearsal, then Live for the grill, on card 1 with the sample answer). It
  took 12 seconds. The investor's follow-up went straight at the error code had flagged: "You said 18
  months. The pack says 17. Which is it? And 'Q2 next year' isn't a date." Coaching: clarity
  3/5, use of data 2/5, root cause 2/5. Every figure in it passed the checker (net new ARR
  -31.7% YoY, NRR 109% vs 119%, $34.2M cash). Merged into demo_cache/cache.json, and the
  demo test now runs instead of skipping.
- **Chat history:** Brandon couldn't find Cowork's export options, so the agent built
  `agent_chat_history.md` from the session transcript in its own workspace. It includes
  every message and reply, one line per tool action with test results, and leaves out tool
  outputs and private reasoning. Screened for email addresses, other job searches, keys and
  tokens.
- **Loom script and cover email** drafted in Brandon's voice in a separate doc.
- 139 tests pass.
