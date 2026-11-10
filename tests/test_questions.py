import pytest

from engine.llm import LLM, DemoCache, DemoCacheMiss, LLMError, call_json, parse_json
from engine.questions import generate_candidates, load_personas, make_validator, rank
from engine.verify import allowed_numbers, verify_questions
from tests.conftest import FakeClient


def test_three_personas_parsed():
    ids = [p.id for p in load_personas()]
    assert ids == ["growth_vc", "independent_director", "cash_investor"]


def test_prompt_contains_computed_inputs(fake_llm, pack, report, bva):
    generate_candidates(fake_llm, pack, report, bva)
    prompt = fake_llm.client.calls[0]
    assert "NRR_DECLINE" in prompt and "Q3 2026" in prompt and "THRESHOLDS" in prompt
    assert "{" not in prompt.split("OUTPUT")[0].replace("{\n", "").split("SIGNALS")[0]  # template filled


def test_uncited_questions_are_dropped(fake_llm, pack, report, bva):
    cands, errors = generate_candidates(fake_llm, pack, report, bva)
    assert errors == []
    assert len(cands) == 14                                    # 15 minus the uncited one
    assert not any("How is the business doing" in c.question for c in cands)


def test_rank_top10_covers_every_flag_without_duplicates(fake_llm, pack, report, bva):
    cands, _ = generate_candidates(fake_llm, pack, report, bva)
    top = rank(cands, report)
    assert len(top) == 10
    covered = {s for q in top for s in q.signal_ids}
    assert covered == {f.id for f in report.flags}             # all 7, incl. the positive story
    texts = [q.question for q in top]
    assert sum("when do you need to raise" in t or "when exactly do you need to raise" in t for t in texts) == 1
    for pid in ("growth_vc", "independent_director", "cash_investor"):
        assert sum(q.persona_id == pid for q in top) <= 4
    assert [q.rank for q in top] == list(range(1, 11))
    assert top[0].score >= top[-1].score


def test_verifier_catches_the_invented_number(fake_llm, pack, report, bva):
    cands, _ = generate_candidates(fake_llm, pack, report, bva)
    allowed = allowed_numbers(pack, report, bva)
    verify_questions(cands, allowed)
    bad = {c.question[:40]: [m.text for m in c.extra["verification"].mismatches]
           for c in cands if not c.extra["verification"].ok}
    assert bad == {"Is your plan to bring NRR back to 125% r": ["125%", "125%"]}


def test_retry_once_on_bad_json(tmp_path, pack, report, bva):
    client = FakeClient(broken_first=True)
    llm = LLM(client=client, cache=DemoCache(tmp_path / "c.json"))
    cands, errors = generate_candidates(llm, pack, report, bva)
    assert errors == [] and len(client.calls) == 4             # 3 personas + 1 retry
    assert sum("could not be used" in c for c in client.calls) == 1   # calls run in parallel


def test_two_bad_replies_give_a_friendly_error():
    class Broken:
        def complete(self, s, u):
            return "no json here"
    with pytest.raises(LLMError, match="invalid output twice"):
        call_json(Broken(), "s", "u", lambda o: o)


def test_parse_json_tolerates_fences_and_chatter():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": 2} hope it helps') == {"a": 2}


def test_validator_rejects_short_outline():
    p = load_personas()[0]
    with pytest.raises(ValueError, match="3 bullets"):
        make_validator({"NRR_DECLINE"}, p)({"questions": [
            {"question": "q", "signal_ids": ["NRR_DECLINE"], "answer_outline": ["one"]}]})


def test_live_run_fills_cache_and_demo_mode_replays_it(tmp_path, pack, report, bva):
    cache = DemoCache(tmp_path / "cache.json")
    live, _ = generate_candidates(LLM(client=FakeClient(), cache=cache), pack, report, bva)
    demo_llm = LLM(client=None, cache=DemoCache(tmp_path / "cache.json"))
    demo_llm.mode = "demo"
    replay, errors = generate_candidates(demo_llm, pack, report, bva)
    assert errors == [] and [q.question for q in replay] == [q.question for q in live]


def test_demo_mode_without_cache_says_so(tmp_path, pack, report, bva):
    llm = LLM(client=None, cache=DemoCache(tmp_path / "empty.json"))
    llm.mode = "demo"
    cands, errors = generate_candidates(llm, pack, report, bva)
    assert cands == [] and len(errors) == 3 and "Northbeam sample" in errors[0]


def test_one_positive_story_question_and_persona_fit_wins(fake_llm, pack, report, bva):
    cands, _ = generate_candidates(fake_llm, pack, report, bva)
    top = rank(cands, report)
    positive_led = [q for q in top if q.signal_ids[0] == "ENTERPRISE_LOGOS"]
    assert len(positive_led) == 1
    # ENTERPRISE_LOGOS is in the Growth VC's lane, so her version beats the Cash Investor's.
    assert positive_led[0].persona_id == "growth_vc"


def test_rank_fills_ten_when_caps_are_tight(fake_llm, pack, report, bva):
    from engine import questions as qmod
    cands, _ = generate_candidates(fake_llm, pack, report, bva)
    old = qmod.MAX_PER_PERSONA
    try:
        qmod.MAX_PER_PERSONA = 2          # strict passes alone would stop at 6
        top = rank(cands, report, per_persona=2)
    finally:
        qmod.MAX_PER_PERSONA = old
    assert len(top) == 10
    texts = [q.question for q in top]
    assert len(set(texts)) == 10


def test_truncated_reply_is_retried_then_explained():
    from engine.llm import TruncatedReply

    class CutOff:
        calls = 0
        def complete(self, s, u):
            CutOff.calls += 1
            raise TruncatedReply("the reply was cut off at the token limit")
    with pytest.raises(LLMError, match="cut off at the token limit"):
        call_json(CutOff(), "s", "u", lambda o: o)
    assert CutOff.calls == 2


def test_one_persona_crashing_does_not_take_down_the_rest(tmp_path, pack, report, bva):
    class Flaky(FakeClient):
        def complete(self, system, user):
            if "\nThe Skeptical Independent Director\n- Seat" in user:
                raise RuntimeError("boom")
            return super().complete(system, user)
    llm = LLM(client=Flaky(), cache=DemoCache(tmp_path / "c.json"))
    cands, errors = generate_candidates(llm, pack, report, bva)
    assert len(errors) == 1 and "Independent Director" in errors[0] and "RuntimeError" in errors[0]
    assert {c.persona_id for c in cands} == {"growth_vc", "cash_investor"}
