"""Boardroom Rehearsal — Streamlit UI.

Run: pip install -r requirements.txt && streamlit run app.py
"""
from __future__ import annotations

import re

import streamlit as st

from engine import brief, pipeline
from engine.kpis import METRIC_INFO, SchemaError, load_budget_vs_actual, load_kpis
from engine.llm import LLM
from engine.peers import threads_by_id
from engine.signals import evaluate, fmt

SEVERITY_BADGE = {"red": "🔴 Red", "amber": "🟠 Amber", "positive": "🟢 Positive"}

st.set_page_config(page_title="Boardroom Rehearsal", page_icon="📋", layout="wide")


def esc(text: str) -> str:
    """Streamlit markdown reads $...$ as a math formula; show dollar signs literally."""
    return str(text).replace("$", r"\$")


# Built fresh on each run (cheap). Caching it with st.cache_resource kept a client from
# an older version of the code alive after a redeploy, so its errors slipped past
# the new code's `except LLMError`.
ss = st.session_state
live_llm = LLM()

# ---- Sidebar: data and mode ----------------------------------------------------
with st.sidebar:
    st.header("Board pack")
    if st.button("Load Northbeam Q3 board pack", type="primary", use_container_width=True):
        ss.pack, ss.bva, ss.result = load_kpis(), load_budget_vs_actual(), None
    upload = st.file_uploader("…or upload a KPI CSV", type=["csv"])
    from engine.kpis import REQUIRED_COLUMNS, SAMPLE_KPIS
    st.download_button("Download the CSV template", SAMPLE_KPIS.read_bytes(), "board_kpis_template.csv",
                       "text/csv", help="The Northbeam sample in the expected format. Required columns: "
                       + ", ".join(REQUIRED_COLUMNS) + ". Money in $M, rates in %.")
    if upload is not None and ss.get("upload_name") != upload.name:
        try:
            ss.pack, ss.bva, ss.result = load_kpis(upload, source="upload"), None, None
            ss.upload_name = upload.name
        except SchemaError as exc:
            st.error(str(exc))
    st.divider()
    st.header("AI mode")
    is_sample = ss.get("pack") is None or ss.get("pack").source == "sample"
    if live_llm.mode == "live":
        options = ["Instant demo (saved run)", "Live AI run"] if is_sample else ["Live AI run"]
        choice = st.radio("Mode", options, label_visibility="collapsed",
                          help="The demo replays a saved live run of the Northbeam sample, with every "
                               "check re-run. A live run calls Claude (about 90 seconds).")
    else:
        choice = "Instant demo (saved run)"
    if choice == "Live AI run":
        llm = live_llm
        st.success(f"Live · {llm.model}")
    else:
        llm = LLM(client=None)
        llm.mode = "demo"
        st.info("Demo · replays a saved live run. Every figure, citation and count is re-checked by code."
                + ("" if live_llm.mode == "live" else " No API key needed."))
    st.caption("All data is synthetic. Northbeam Analytics is a fictional company; "
               "peer CFO threads are fictional.")

# ---- Header ---------------------------------------------------------------------
st.title("Boardroom Rehearsal")
st.markdown("Walk into the board meeting having already heard the 10 hardest questions, with answer "
            "outlines grounded in your numbers and how peer CFOs handled the same questions.")
st.caption("① Code flags what the board will probe  ·  ② three AI board members ask, code ranks the "
           "top 10  ·  ③ every figure is checked against the KPI table  ·  ④ peer threads are matched in "
           "code, and every peer insight cites its thread")

pack = ss.get("pack")
if pack is None:
    st.info("**Try it in 60 seconds:** click **Load Northbeam Q3 board pack** in the sidebar, then "
            "**Rehearse**. Northbeam Analytics is a fictional Series C SaaS company.")
    st.stop()

report = evaluate(pack)
for issue in pack.issues:
    st.warning(esc(issue))

# ---- 1. Risk signals --------------------------------------------------------------
st.subheader(f"1 · Risk signals for {pack.quarter}")
st.caption("Computed in code from the rules in signals.yaml. No AI involved.")
if not report.flags:
    st.success("No rules fired for this quarter. Nothing stands out for the board to probe.")
for f in report.flags:
    c1, c2 = st.columns([1, 5])
    c1.markdown(f"**{SEVERITY_BADGE[f.severity]}**")
    c2.markdown(f"**{f.label}** `{f.id}`  \n{esc(f.description)}  \n"
                f"<span style='color:gray;font-size:0.85em'>Rule: {f.threshold}</span>",
                unsafe_allow_html=True)
if report.skipped:
    with st.expander("Rules that couldn't run on this data"):
        for s in report.skipped:
            st.write("• " + esc(s))
with st.expander("KPI table"):
    st.dataframe(pack.df.rename(columns={k: f"{v[0]} ({v[1]})" for k, v in METRIC_INFO.items()}),
                 hide_index=True, use_container_width=True)

# ---- 2. The hard 10 -----------------------------------------------------------------
st.subheader("2 · The hard 10")
needs_live = llm.mode == "demo" and pack.source != "sample"
if needs_live:
    st.info("The instant demo only covers the Northbeam sample. Rehearsing your own pack needs a live AI run"
            + (": choose **Live AI run** in the sidebar." if live_llm.mode == "live"
               else ", which needs an ANTHROPIC_API_KEY (see the README). The risk signals above are computed "
                    "in code and work without one."))
if st.button("Rehearse", type="primary", disabled=not report.flags or needs_live):
    with st.status("Rehearsing…", expanded=True) as status:
        st.write("Three board members are reading the pack…")
        res = pipeline.run(llm, pack, ss.get("bva"), report, with_peers=False)
        st.write(f"Ranked the top {len(res.top)}. Finding how peer CFOs handled each one…")
        ss.result = pipeline.add_peers(llm, res) if res.top else res
        status.update(label="Rehearsal ready", state="complete", expanded=False)

result = ss.get("result")
if result is None:
    st.caption("Click **Rehearse** to generate the board's questions.")
    st.stop()

for e in result.errors:
    st.warning(esc(e))

if result.top:
    n_checked = len(result.verification.checks)
    if result.verification.ok:
        st.success(f"✅ All figures verified: {n_checked} numbers checked against the KPI table.")
    peers = [q.extra.get("peers") for q in result.top if q.extra.get("peers")]
    if peers:
        close = sum(p.coverage == "close" for p in peers)
        drafts = sum(bool(p.draft) for p in peers)
        st.caption(f"Peer layer: {close} of {len(result.top)} questions have close peer threads; "
                   f"{drafts} Braintrust draft(s) for questions peers haven't covered. "
                   "Peer threads are synthetic.")
    else:
        st.error(f"{len(result.verification.mismatches)} figure(s) didn't match the KPI table.")

flags = report.by_id()
threads = threads_by_id()


def cite(ids: list[str]) -> str:
    return " ".join(f"`{t}`" for t in ids)


def render_peers(q) -> None:
    p = q.extra.get("peers")
    if p is None:
        return
    st.markdown("---")
    if p.coverage == "close":
        st.markdown("#### 🤝 How peers handled it")
    elif p.coverage == "topic":
        st.markdown("#### 🤝 How peers handled the topic")
        st.caption("Peers have discussed this area, but not this exact question. A draft for the Braintrust is below.")
    else:
        st.markdown("#### 🤝 No peer threads on this yet")
    if p.facts:   # computed in code, shown as data
        f = p.facts
        stages = ", ".join(f"{k} {v}" for k, v in f["stages"].items())
        st.caption(f"{f['replies']} replies across {f['threads']} thread(s) · {f['pushback_replies']} pushed back · "
                   f"{stages} · counted in code")
    s = p.summary
    if s:
        if s["headline"]:
            st.markdown(f"**{esc(s['headline'])}**")
        for pt in s["points"]:
            c = pt.get("count")
            lead = f"**{c['replies']} of {c['of']} replies** {esc(c['label'])}. " if c else ""
            st.markdown(f"- {lead}{esc(pt['text'])} {cite(pt['thread_ids'])}")
        if s.get("split"):
            st.markdown(f"**Where peers disagree:** {esc(s['split']['text'])} {cite(s['split']['thread_ids'])}")
        if s.get("stage_note"):
            st.markdown(f"*{esc(s['stage_note'])}*")
        st.caption("Counts in bold are computed in code from reply tags; the AI wrote the sentences."
                   + (f" {len(s['dropped'])} AI point(s) dropped by the checks." if s.get("dropped") else ""))
    if p.matches:
        with st.popover("Read the peer threads (synthetic)"):
            for m in p.matches:
                t = threads[m.thread_id]
                a = t["asked_by"]
                st.markdown(f"**`{t['id']}` {esc(t['title'])}**  \n"
                            f"<span style='color:gray;font-size:0.85em'>Asked by a {a['stage']} {a['industry']} CFO "
                            f"({esc(a['arr_band'])} ARR) · {t['posted']} · match {m.score:.2f}</span>",
                            unsafe_allow_html=True)
                st.markdown(f"> {esc(t['question'])}")
                for r in t["replies"]:
                    tag = " · *pushed back*" if r.get("dissent") else ""
                    st.markdown(f"- **{r['stage']}, {r['industry']}**{tag}: {esc(r['text'])}")
    if p.draft:
        st.markdown("**Ask the Braintrust** (anonymous draft: no company name, figures as ranges)")
        st.text_input("Title", p.draft["title"], key=f"bt_title_{q.rank}")
        st.text_area("Question", p.draft["question"], key=f"bt_q_{q.rank}", height=110)
        if st.button("Post to the Braintrust (mock)", key=f"bt_post_{q.rank}"):
            st.info("Prototype: nothing was posted. In Floyd this would go to peers matched on stage and topic, "
                    "and their answers would feed the next CFO's prep.")


for q in result.top:
    with st.expander(f"**{q.rank}. {q.persona_name}** — {esc(q.question)}"):
        st.markdown(f"**Why they'll ask:** {esc(q.why_they_ask)}")
        st.markdown("**The data behind it** (computed in code):")
        for sid in q.signal_ids:
            f = flags[sid]
            st.markdown(f"- {SEVERITY_BADGE[f.severity]} `{sid}` {esc(f.description)}")
        st.markdown("**Answer outline:**")
        for label, bullet in zip(("Headline", "Evidence", "Action"), q.answer_outline):
            st.markdown(f"- *{label}:* {esc(re.sub(rf'^{label}\s*:\s*', '', bullet, flags=re.I))}")
        st.markdown(f"**Trap to avoid:** {esc(q.trap_to_avoid)}")
        v = q.extra["verification"]
        st.caption(esc("Figures checked: " + (", ".join(f"{c.text} ✓" for c in v.checks) or "none")))
        render_peers(q)

# ---- 3. Board prep brief ------------------------------------------------------------
if result.top:
    st.subheader("3 · Take it into the room")
    mode_label = "Live AI run" if llm.mode == "live" else "Instant demo (saved live run)"
    fname = f"board_prep_brief_{pack.quarter.replace(' ', '_')}"
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button("Download brief (.docx)", brief.to_docx(result, mode_label), f"{fname}.docx",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       type="primary", use_container_width=True)
    c2.download_button("Download brief (.md)", brief.to_markdown(result, mode_label), f"{fname}.md",
                       "text/markdown", use_container_width=True)
    st.caption("Page 1–2: the hard 10 at a glance (what to say, what to avoid, what peers did). "
               "Appendix: full outlines, peer insights with thread citations, Braintrust drafts.")

if result.held_back:
    with st.expander(f"Held back by the verifier ({len(result.held_back)})"):
        st.caption("These candidates quoted a figure that isn't in the KPI table, so they were not shown above.")
        for q in result.held_back:
            bad = "; ".join(f"**{c.text}** in “{c.context}” ({c.source})"
                            for c in q.extra["verification"].mismatches)
            st.markdown(esc(f"- *{q.persona_name}:* {q.question}  \n  **Unverified:** {bad}"))

# ---- Save this run for demo mode (live mode only) ----------------------------------
if llm.mode == "live" and getattr(result, "ai_calls", 0):   # older session objects lack it
    st.divider()
    st.download_button(
        f"Save this run as the demo cache ({result.ai_calls} AI outputs)",
        llm.cache.export(result.run_id), "cache.json", "application/json",
        help="Exactly this run's AI outputs. Committed to demo_cache/, it lets the app run without a key.")
