import json

import pytest

from engine.grill import check_answer, grill, sample_answer
from engine.llm import LLM, DemoCache, LLMError
from engine.questions import Question
from engine.verify import allowed_numbers

Q1 = Question(persona_id="cash_investor", persona_name="The Cash-Focused Lead Investor",
              question="At a 2.1x burn multiple and 17 months of runway, when do you need to raise, and on what story?",
              signal_ids=["BURN_MULTIPLE", "RUNWAY"], why_they_ask="w",
              answer_outline=["Headline: a date.", "Evidence: 2.1x vs 1.5x; 17 months.", "Action: downside plan."],
              trap_to_avoid="t", rank=1)


class Coach:
    """Stand-in for the AI board member; returns whatever reply the test sets."""
    model = "fake"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, system, user):
        self.calls.append(user)
        return json.dumps(self.reply)


def _reply(follow="You said 18 months. It's 17. When exactly do you start?", why="Led with timing."):
    return {"follow_up": follow,
            "scores": {k: {"score": 3, "why": why} for k in ("clarity", "use_of_data", "root_cause")},
            "strongest": "Named enterprise as the story.", "fix": "Lead with the date and the 17 months."}


@pytest.fixture
def allowed(pack, report, bva):
    return allowed_numbers(pack, report, bva)


def test_code_checks_the_cfos_own_figures(pack, allowed):
    c = check_answer("We have about 18 months of runway, burn is $6M a quarter and logos are up 40%.", allowed, pack)
    assert c.notes == ["You said 18 months; the pack shows runway of 17 months in Q3 2026."]
    assert check_answer("Burn multiple is 2.1x and runway is 17 months.", allowed, pack).ok


def test_follow_up_gets_the_code_findings(tmp_path, pack, report, allowed):
    coach = Coach(_reply())
    llm = LLM(client=coach, cache=DemoCache(tmp_path / "c.json"))
    check, out = grill(llm, Q1, "We have about 18 months of runway.", pack, report, allowed)
    assert "You said 18 months; the pack shows runway of 17 months" in coach.calls[0]
    assert out["scores"]["clarity"]["score"] == 3


def test_feedback_may_quote_the_cfos_wrong_figure_but_not_invent_one(tmp_path, pack, report, allowed):
    ok = LLM(client=Coach(_reply()), cache=DemoCache(tmp_path / "a.json"))
    grill(ok, Q1, "We have about 18 months of runway.", pack, report, allowed)       # "18 months" is the CFO's
    bad = LLM(client=Coach(_reply(follow="Runway is really 11 months, isn't it?")), cache=DemoCache(tmp_path / "b.json"))
    with pytest.raises(LLMError, match="invalid output twice"):
        grill(bad, Q1, "We have about 18 months of runway.", pack, report, allowed)


def test_scores_must_be_one_to_five(tmp_path, pack, report, allowed):
    r = _reply(); r["scores"]["clarity"]["score"] = 9
    with pytest.raises(LLMError):
        grill(LLM(client=Coach(r), cache=DemoCache(tmp_path / "c.json")), Q1, "x", pack, report, allowed)


def test_sample_answer_has_one_deliberate_mistake(pack, allowed):
    s = sample_answer(Q1.question)
    assert s and len(check_answer(s, allowed, pack).notes) == 1
    assert sample_answer("Some other question") is None
