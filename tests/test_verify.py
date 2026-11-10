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
