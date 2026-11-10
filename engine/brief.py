"""Board prep brief: the rehearsal on paper (.md and .docx).

Every number in the brief comes from the rehearsal result: signal descriptions and
peer counts from code, question text from AI output that already passed the verifier.
Nothing is recomputed or reworded here.
"""
from __future__ import annotations

import io
import re
from datetime import date

from engine.pipeline import Rehearsal

SEV = {"red": "RED", "amber": "AMBER", "positive": "POSITIVE"}
LABEL_RE = re.compile(r"^(Headline|Evidence|Action)\s*:\s*", re.I)


def _outline(q) -> list[tuple[str, str]]:
    return [(label, LABEL_RE.sub("", b)) for label, b in zip(("Headline", "Evidence", "Action"), q.answer_outline)]


def _peer_lines(q) -> tuple[str | None, list[str], str | None, dict | None]:
    p = q.extra.get("peers")
    if not p or not p.summary:
        return None, [], None, (p.draft if p else None)
    s = p.summary
    points = []
    for pt in s["points"][:2]:
        c = pt.get("count")
        lead = f"{c['replies']} of {c['of']} replies {c['label']}. " if c else ""
        points.append(f"{lead}{pt['text']} [{', '.join(pt['thread_ids'])}]")
    split = f"{s['split']['text']} [{', '.join(s['split']['thread_ids'])}]" if s.get("split") else None
    return s.get("headline") or None, points, split, p.draft


def _header(r: Rehearsal, mode: str) -> list[str]:
    checks = len(r.verification.checks)
    return [
        f"Board prep brief: {r.pack.quarter}",
        f"Prepared {date.today():%B %-d, %Y} · {mode} · {checks} figures verified against the KPI table · "
        "synthetic data (Northbeam Analytics and peer CFOs are fictional)",
    ]


def to_markdown(r: Rehearsal, mode: str = "Boardroom Rehearsal") -> str:
    title, sub = _header(r, mode)
    out = [f"# {title}", f"*{sub}*", "", "## What the board will probe", ""]
    for f in r.report.flags:
        out.append(f"- **{SEV[f.severity]} · {f.label}** — {f.description}")
    out += ["", "## The hard 10 at a glance", ""]
    for q in r.top:
        headline, _, _, draft = _peer_lines(q)
        say = _outline(q)[0][1] if q.answer_outline else ""
        out += [f"**{q.rank}. {q.persona_name}:** {q.question}",
                f"- *Say:* {say}", f"- *Avoid:* {q.trap_to_avoid}"]
        if headline:
            out.append(f"- *Peers:* {headline}")
        elif draft:
            out.append("- *Peers:* not covered yet; Braintrust draft in the appendix.")
        out.append("")
    out += ["---", "", "## Appendix: full outlines and peer insights", ""]
    for q in r.top:
        out += [f"### {q.rank}. {q.persona_name}", "", f"> {q.question}", "",
                f"*Why they'll ask:* {q.why_they_ask}", ""]
        out += [f"- **{label}:** {text}" for label, text in _outline(q)]
        out += ["", f"**Trap to avoid:** {q.trap_to_avoid}", ""]
        headline, points, split, draft = _peer_lines(q)
        if headline or points:
            out.append(f"**How peers handled it:** {headline or ''}")
            out += [f"- {p}" for p in points]
            if split:
                out.append(f"- *Where peers disagree:* {split}")
            out.append("")
        if draft:
            out += [f"**Ask the Braintrust (draft):** *{draft['title']}* — {draft['question']}", ""]
    out += ["---", "*Counts of peer replies are computed in code from reply tags. "
            "Every figure in the questions and outlines was checked against the computed KPI table.*"]
    return "\n".join(out)


def to_docx(r: Rehearsal, mode: str = "Boardroom Rehearsal") -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor

    title, sub = _header(r, mode)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name, style.font.size = "Calibri", Pt(9.5)
    for sec in doc.sections:   # tighter margins so the cheat sheet fits two pages
        from docx.shared import Inches
        sec.left_margin = sec.right_margin = Inches(0.7)
        sec.top_margin = sec.bottom_margin = Inches(0.6)
    doc.add_heading(title, level=0)
    p = doc.add_paragraph(sub)
    p.runs[0].italic = True
    p.runs[0].font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    doc.add_heading("What the board will probe", level=1)
    for f in r.report.flags:
        para = doc.add_paragraph(style="List Bullet")
        para.add_run(f"{SEV[f.severity]} · {f.label}: ").bold = True
        para.add_run(f.description)

    doc.add_heading("The hard 10 at a glance", level=1)
    for q in r.top:
        headline, _, _, draft = _peer_lines(q)
        qp = doc.add_paragraph()
        qp.paragraph_format.space_after = Pt(1)
        qp.add_run(f"{q.rank}. {q.persona_name}: ").bold = True
        qp.add_run(q.question)
        lines = [("Say", _outline(q)[0][1]), ("Avoid", q.trap_to_avoid)]
        lines.append(("Peers", headline) if headline else
                     ("Peers", "not covered yet; Braintrust draft in the appendix.") if draft else None)
        for item in filter(None, lines):
            b = doc.add_paragraph(style="List Bullet")
            b.paragraph_format.space_after = Pt(0)
            b.add_run(f"{item[0]}: ").italic = True
            b.add_run(item[1])
    doc.add_page_break()
    doc.add_heading("Appendix: full outlines and peer insights", level=1)
    for q in r.top:
        doc.add_heading(f"{q.rank}. {q.persona_name}", level=2)
        doc.add_paragraph(q.question).runs[0].bold = True
        why = doc.add_paragraph()
        why.add_run("Why they'll ask: ").italic = True
        why.add_run(q.why_they_ask)
        for label, text in _outline(q):
            b = doc.add_paragraph(style="List Bullet")
            b.add_run(f"{label}: ").bold = True
            b.add_run(text)
        trap = doc.add_paragraph()
        trap.add_run("Trap to avoid: ").bold = True
        trap.add_run(q.trap_to_avoid)
        headline, points, split, draft = _peer_lines(q)
        if headline or points:
            h = doc.add_paragraph()
            h.add_run("How peers handled it: ").bold = True
            h.add_run(headline or "")
            for pt in points:
                doc.add_paragraph(pt, style="List Bullet 2")
            if split:
                doc.add_paragraph(f"Where peers disagree: {split}", style="List Bullet 2")
        if draft:
            d = doc.add_paragraph()
            d.add_run("Ask the Braintrust (draft): ").bold = True
            d.add_run(f"{draft['title']}. {draft['question']}")
    foot = doc.add_paragraph("Counts of peer replies are computed in code from reply tags. Every figure in the "
                             "questions and outlines was checked against the computed KPI table.")
    foot.runs[0].italic = True
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
