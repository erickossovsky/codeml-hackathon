from l2c.compare import fusion
from l2c.contract import constants as C
from l2c.match.matcher import Pair
from l2c.mock.elements import make_element


def pair(method="key", margin=None):
    return Pair(
        make_element("plan", "N2", "K", 3), make_element("shop", "N2", "K", 3), method, None, margin
    )


def test_verdict_needs_both_a_difference_and_enough_trust():
    assert fusion.decide_pair(True, 0.9) == "non_compliant"
    assert fusion.decide_pair(True, C.TRUST_MIN_FOR_VERDICT - 0.01) == "needs_review"
    assert fusion.decide_pair(False, 0.95) == "compliant"
    assert fusion.decide_pair(False, 0.5) == "needs_review"


def test_ml_can_escalate_but_never_suppress():
    assert fusion.decide_pair(False, 0.95, anomaly=0.9) == "needs_review"
    assert fusion.decide_pair(False, 0.95, pair_probability=0.7) == "needs_review"
    assert fusion.decide_pair(False, 0.95, anomaly=0.1, pair_probability=0.1) == "compliant"
    assert fusion.decide_pair(True, 0.95, anomaly=0.0, pair_probability=0.0) == "non_compliant"


def test_near_column_matches_are_trusted_less():
    assert fusion.match_factor(pair("key")) == 1.0
    assert fusion.match_factor(pair("near_col", 1.0)) == 0.7
    assert fusion.match_factor(pair("near_col", 0.0)) < fusion.match_factor(pair("near_col", 1.0))


def test_trust_is_the_weaker_extraction_times_the_match_factor():
    p = Pair(
        make_element("plan", "N2", "K", 3, overall=0.6),
        make_element("shop", "N2", "K", 3, overall=0.9),
        "key",
    )
    assert fusion.trust(p.plan, p.shop, p) == 0.6
    assert fusion.trust(None, None, Pair(None, None, "none")) == 0.0


def test_confidence_and_probability():
    assert fusion.confidence(0.8, 1.0, conforming=False) == 0.8
    assert fusion.confidence(0.8, 0.0, conforming=True) == 0.8
    assert fusion.confidence(0.8, 0.0, conforming=True, anomaly=0.5) == 0.4
    assert (
        fusion.discrepancy_probability(True) == 1.0 and fusion.discrepancy_probability(False) == 0.0
    )
    assert fusion.discrepancy_probability(True, 0.4) == 1.0  # a fired rule is never lowered
    assert fusion.discrepancy_probability(False, 0.4) == 0.4
