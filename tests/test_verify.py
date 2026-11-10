import pytest

from engine.verify import allowed_numbers, extract, verify_text


@pytest.fixture
def allowed(pack, report, bva):
    return allowed_numbers(pack, report, bva)


@pytest.mark.parametrize("text", [
    "NRR fell from 118% to 109% in two quarters.",
    "Burn multiple is 2.1x vs 1.5x a year ago.",
    "Gross margin is 72.8%, down 3 points from 75.8%.",
    "Runway is 17 months on $34.17M of cash.",
    "Cash of $34.2M covers 17 months.",                 # rounding to one decimal is fine
    "Pipeline coverage is 2.4x against a 3x target (80% of target).",
    "Net new ARR was $2.87M vs $3.8M plan in Q3 2026 (-24.5%).",
    "Enterprise logos grew 40%, from 30 to 42.",
    "Cost of revenue ran 10.1% over budget: $3.17M vs $2.88M.",
    "Revenue came in at $11.64M against a $12M budget.",
    "Opex of $14.1M landed on budget; ARR is $48M.",
    "Gross margin near 73% after the migration.",        # whole-number rounding of 72.8
    "Net new ARR fell to $2.87M from $4.2M a year ago.",
])
def test_true_figures_pass(text, allowed):
    v = verify_text(text, allowed)
    assert v.checks, "expected at least one figure to be checked"
    assert v.ok, [c.text for c in v.mismatches]


@pytest.mark.parametrize("text, bad", [
    ("Runway is 19 months.", "19 months"),                     # wrong number
    ("Burn multiple is 2.4x.", "2.4x"),                        # real number, wrong unit/metric (2.4 is pipeline)
    ("NRR fell to 107%.", "107%"),
    ("Cash is $41.5M.", "$41.5M"),
    ("ARR grew 45% year over year.", "45%"),                   # a growth rate code never computed
    ("Get NRR back to 125% by next year.", "125%"),            # invented target
    ("Burn multiple is about 2x.", "2x"),                      # 2x is a threshold, not the value (2.1x)
    ("Runway is down to 18 months.", "18 months"),             # 18 is the alert line, not the value
])
def test_wrong_figures_fail(text, bad, allowed):
    v = verify_text(text, allowed)
    assert not v.ok
    assert [c.text for c in v.mismatches] == [bad]


@pytest.mark.parametrize("text", [
    "ARR grew 39.4% year over year.",                          # in TRENDS: computed by code
    "Burn multiple is 2.1x, above the 2x red line.",           # threshold, referred to as one
    "Runway is 17 months, below the 18-month alert line.",
    "Can we get burn multiple back under 1.5x before the raise?",
])
def test_referenced_thresholds_and_trends_pass(text, allowed):
    v = verify_text(text, allowed)
    assert v.ok, [(c.text, c.source) for c in v.mismatches]


def test_deliberately_wrong_number_in_a_real_outline(allowed):
    outline = ("Headline: burn is flat; growth slowed. Evidence: net burn $6.03M a quarter, "
               "burn multiple 2.1x, runway 18 months. Action: cut to 1.5x before the raise.")
    v = verify_text(outline, allowed)
    assert [c.text for c in v.mismatches] == ["18 months"]   # true value is 17 months


def test_dates_counts_and_labels_are_not_figures():
    found = [raw for raw, *_ in extract(
        "In Q3 2026 and FY2026, two quarters running, Series C, 3 bullets, 60 seconds, the 2nd miss.")]
    assert found == []


def test_unit_parsing():
    vals = {raw: (val, cat) for raw, val, cat, _ in extract("$340K, $1.2B, 2.1x, 9 pts, 17 months, 42")}
    assert vals["$340K"] == (pytest.approx(0.34), "usd")
    assert vals["$1.2B"] == (pytest.approx(1200.0), "usd")
    assert vals["2.1x"] == (2.1, "x")
    assert vals["9 pts"] == (9.0, "pct")
    assert vals["17 months"] == (17.0, "months")
    assert vals["42"] == (42.0, None)


# Phrasings from the first live run (2026-11-10) that were wrongly held back.
@pytest.mark.parametrize("text", [
    "17 months of runway puts you inside the board's 18-month comfort line.",
    "Runway is 17 months against an 18-month threshold.",
    "Two consecutive misses beyond 10% point to a structural gap, and pipeline coverage is 2.4x.",
    "Coverage of 2.4x and two misses of more than 10% in a row.",
    "Enterprise logos grew 40%, well above the 25% bar the board uses.",
    "Logo growth of 40% clears the 25% positive threshold.",
])
def test_live_run_false_positives_now_pass(text, allowed):
    v = verify_text(text, allowed)
    assert v.ok, [(c.text, c.source) for c in v.mismatches]


def test_thresholds_still_need_to_be_named_as_such(allowed):
    assert not verify_text("Runway is 18 months.", allowed).ok
    assert not verify_text("Logos grew 25% this year.", allowed).ok


def test_streak_claims_are_checked_against_code(allowed):
    # Live run: "Margin has fallen in each of the last four quarters" (it was three; Q4 2025 was flat).
    bad = verify_text("Margin has fallen in each of the last four quarters.", allowed)
    assert [c.text for c in bad.mismatches] == ["each of the last four quarters"]
    assert verify_text("Gross margin is down three quarters in a row.", allowed).ok
    assert verify_text("You missed plan two quarters in a row.", allowed).ok         # FORECAST_MISS count
    assert not verify_text("Pipeline coverage fell six straight quarters.", allowed).ok   # it is 5
    assert verify_text("Pipeline coverage fell five straight quarters.", allowed).ok


def test_plan_change_is_a_computed_figure(allowed):
    # Live run 2: "The Q3 plan ... was only $0.1M lower" (3.9 -> 3.8). Now a code-computed trend.
    assert verify_text("The Q3 plan was set after the Q2 miss and was only $0.1M lower.", allowed).ok
    assert not verify_text("The Q3 plan was $0.4M lower.", allowed).ok


# Live run 4: held back wrongly.
@pytest.mark.parametrize("text", [
    "Using the 40% logo growth as proof the business is healthy while ignoring that NRR and net new ARR are both falling.",
    "A 9-point drop in retention undermines the revenue plan.",
    "Runway is 17 months, inside the 18-month line.",
])
def test_live_run_4_false_positives_now_pass(text, allowed):
    v = verify_text(text, allowed)
    assert v.ok, [(c.text, c.source) for c in v.mismatches]


def test_hyphenated_units_parse():
    vals = {raw: (val, cat) for raw, val, cat, _ in extract("a 9-point drop, an 18-month line")}
    assert vals["9-point"] == (9.0, "pct") and vals["18-month"] == (18.0, "months")
    assert not verify_text("A 7-point drop in retention.", allowed_numbers(*_sample())).ok


def _sample():
    from engine.kpis import load_budget_vs_actual, load_kpis
    from engine.signals import evaluate
    p = load_kpis()
    return p, evaluate(p), load_budget_vs_actual()


def test_metric_named_in_a_later_clause_does_not_claim_the_figure(allowed):
    # Live cache: "-20.5%" was matched to "coverage", which comes after the semicolon.
    text = "Evidence: Q2 was $3.1M vs $3.9M (-20.5%) and Q3 was $2.87M vs $3.8M (-24.5%); coverage is 2.4x vs the 3x target."
    v = verify_text(text, allowed)
    assert v.ok, [(c.text, c.source) for c in v.mismatches]


def test_point_change_can_refer_to_the_cards_metric(allowed):
    # Live run 5: the card is about NRR; the trap sentence only names GRR.
    card = ("NRR is 109%, down from 118% in Q1 2026. "
            "Pointing to the still-healthy GRR to downplay the decline, when a 9-point drop is the story.")
    assert verify_text(card, allowed).ok
    # ...but only for point changes the code computed, and only for metrics the card names.
    assert not verify_text("Pointing to GRR, when a 7-point drop is the story. NRR is 109%.", allowed).ok
    assert not verify_text("GRR held, but there was a 9-point drop.", allowed).ok
