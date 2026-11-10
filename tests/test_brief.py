import io

from docx import Document

from engine import brief, pipeline
from engine.llm import LLM


def _run(pack, report, bva):
    llm = LLM(client=None); llm.mode = "demo"        # the committed demo cache
    return pipeline.run(llm, pack, bva, report)


def test_markdown_brief_has_cheat_sheet_then_appendix(pack, report, bva):
    r = _run(pack, report, bva)
    md = brief.to_markdown(r, "Instant demo (saved live run)")
    glance, appendix = md.index("## The hard 10 at a glance"), md.index("## Appendix")
    assert glance < appendix
    for q in r.top:
        assert q.question in md[glance:appendix]                  # every question on the cheat sheet
    assert md.count("- *Say:*") == 10 and md.count("- *Avoid:*") == 10
    assert "fictional" in md and f"{len(r.verification.checks)} figures verified" in md
    assert "replies" in md[appendix:]                             # code-made peer counts in the appendix


def test_brief_only_reuses_checked_text(pack, report, bva):
    r = _run(pack, report, bva)
    md = brief.to_markdown(r)
    for f in r.report.flags:
        assert f.description in md                                # signal lines are the code's own sentences


def test_docx_brief_opens(pack, report, bva):
    r = _run(pack, report, bva)
    doc = Document(io.BytesIO(brief.to_docx(r)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "The hard 10 at a glance" in text and "Appendix" in text
    assert text.count("Say: ") == 10
