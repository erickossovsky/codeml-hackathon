"""cross.plan_vs_shop: one finding per match pair (compliant, non_compliant, missing, added)."""

from __future__ import annotations

import hashlib

from l2c.compare import fusion
from l2c.compare.profile import generic_diffs, profile, profile_diffs
from l2c.contract import constants as C
from l2c.contract.models import (
    ElementExt,
    Evidence,
    ExtractionEvidence,
    Finding,
    MatchEvidence,
    Ref,
    RuleEvidence,
)
from l2c.match.matcher import Pair


def ref(e: ElementExt | None) -> Ref | None:
    if e is None:
        return None
    return Ref(element_id=e.id, fichier=e.fichier, page=e.page, x=e.x, y=e.y)


def finding_id(check_type: str, *parts: str | None) -> str:
    raw = "|".join([check_type, *[p or "" for p in parts]])
    return "F-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def compare_pair(pair: Pair, plan_levels: set[str], shop_levels: set[str]) -> Finding:
    plan, shop = pair.plan, pair.shop
    anchor = plan or shop
    assert anchor is not None
    key = anchor.match_key
    t = fusion.trust(plan, shop, pair)
    notes = ""
    diffs = []
    kind = "field_diff"
    if plan and shop:
        diffs = (
            profile_diffs(profile(plan), profile(shop))
            if key.type == "colonne"
            else generic_diffs(plan, shop)
        )
        fired = bool(diffs)
        status = fusion.decide_pair(fired, t)
        conforming = not fired  # no difference found; low trust only lowers the confidence
    elif plan:
        kind = "missing"
        fired = True
        if pair.method == "unbound":
            kind, status, notes = (
                "unbound_plan_block",
                C.STATUS_NEEDS_REVIEW,
                "block not bound to a grid cell",
            )
        elif plan.level not in shop_levels:
            kind, status, notes = (
                "level_not_covered",
                C.STATUS_NEEDS_REVIEW,
                "no shop data for this level",
            )
        else:
            status = C.STATUS_MISSING if t >= C.TRUST_MIN_FOR_VERDICT else C.STATUS_NEEDS_REVIEW
        conforming = False
    else:
        assert shop is not None
        kind = "added"
        fired = True
        if pair.method == "unbound":
            kind, status, notes = (
                "unbound_shop_block",
                C.STATUS_NEEDS_REVIEW,
                "block not bound to a grid cell",
            )
        elif shop.level not in plan_levels:
            kind, status, notes = (
                "level_not_covered",
                C.STATUS_NEEDS_REVIEW,
                "level has no plan sheet in scope",
            )
        else:
            status = C.STATUS_ADDED if t >= C.TRUST_MIN_FOR_VERDICT else C.STATUS_NEEDS_REVIEW
        conforming = False
    prob = fusion.discrepancy_probability(fired and not conforming)
    return Finding(
        id=finding_id(
            "cross.plan_vs_shop", plan.id if plan else None, shop.id if shop else None, kind
        ),
        check_type="cross.plan_vs_shop",
        status=status,  # type: ignore[arg-type]
        type_element=key.type,
        level=key.level,
        grid=anchor.grid,
        plan_ref=ref(plan),
        shop_ref=ref(shop),
        diffs=diffs,
        evidence=Evidence(
            rule=RuleEvidence(fired=fired and not conforming, kind=kind, diffs=diffs),
            extraction=ExtractionEvidence(
                plan_overall=plan.quality.overall if plan else None,
                shop_overall=shop.quality.overall if shop else None,
                flags=sorted(
                    {*(plan.quality.flags if plan else []), *(shop.quality.flags if shop else [])}
                ),
            ),
            match=MatchEvidence(
                method=pair.method, assignment_cost=pair.cost, margin_to_runner_up=pair.margin
            ),
        ),
        trust=t,
        discrepancy_probability=prob,
        confidence=fusion.confidence(t, prob, conforming),
        notes=notes,
    )
