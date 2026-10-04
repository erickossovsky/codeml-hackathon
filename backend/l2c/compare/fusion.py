"""Trust, status and confidence (spec 10.22). ML may escalate a verdict, never suppress one."""

from __future__ import annotations

from l2c.contract import constants as C
from l2c.contract.models import ElementExt
from l2c.match.matcher import Pair


def match_factor(pair: Pair) -> float:
    if pair.method == "near_col":
        margin = 1.0 if pair.margin is None else pair.margin
        return round(0.7 * (0.6 + 0.4 * margin), 3)
    return 1.0


def trust(plan: ElementExt | None, shop: ElementExt | None, pair: Pair) -> float:
    overalls = [e.quality.overall for e in (plan, shop) if e is not None]
    return round(min(overalls) * match_factor(pair), 3) if overalls else 0.0


def decide_pair(
    rule_fired: bool,
    trust_value: float,
    anomaly: float | None = None,
    pair_probability: float | None = None,
) -> str:
    """Status for a matched pair: compliant, non_compliant or needs_review."""
    if rule_fired:
        return (
            C.STATUS_NON_COMPLIANT
            if trust_value >= C.TRUST_MIN_FOR_VERDICT
            else C.STATUS_NEEDS_REVIEW
        )
    escalate = (anomaly is not None and anomaly >= C.ANOMALY_ESCALATE) or (
        pair_probability is not None and pair_probability >= C.PAIR_PROB_ESCALATE
    )
    if escalate or trust_value < C.TRUST_MIN_FOR_VERDICT:
        return C.STATUS_NEEDS_REVIEW
    return C.STATUS_COMPLIANT


def discrepancy_probability(rule_fired: bool, pair_probability: float | None = None) -> float:
    if pair_probability is not None:
        return round(max(pair_probability, 1.0 if rule_fired else 0.0), 3)
    return 1.0 if rule_fired else 0.0


def confidence(
    trust_value: float, probability: float, conforming: bool, anomaly: float | None = None
) -> float:
    if conforming:
        return round(trust_value * (1.0 - (anomaly or 0.0)), 3)
    return round(trust_value * probability, 3)
