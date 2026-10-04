"""Run every comparison on a metadata bundle. Pure function of the bundle; deterministic."""

from __future__ import annotations

from l2c.compare import fusion
from l2c.compare.cross import compare_pair
from l2c.compare.duplicates import duplicate_findings
from l2c.compare.self_checks import (
    internal_consistency_findings,
    outlier_finding,
    peer_outliers,
    plausibility_findings,
)
from l2c.contract import constants as C
from l2c.contract.io import MetaBundle
from l2c.contract.models import Finding, MlEvidence
from l2c.match.matcher import match

MIN_PAIRS_TO_LEARN = 50  # below this the project is too small to train a model on itself


def add_pair_probabilities(findings: list[Finding], bundle: MetaBundle) -> list[Finding]:
    """Attach a learned probability to every matched pair, trained on this project's own pairs.

    No labels are needed: the model learns from mutations of the project's agreeing pairs and
    from the project's own weak-extraction flags (see compare/ml/dataset.py). The statuses it may
    change are limited to *raising* a no-difference pair to needs_review; a deterministic
    non_compliant/missing/added verdict is never lowered.
    """
    try:
        from l2c.compare.ml import pair_model
        from l2c.compare.ml.dataset import build_dataset_from_bundle
    except ImportError:  # the learned tier (plan task I9) is optional: fall back to rules only
        return findings

    agreeing = [
        f
        for f in findings
        if f.check_type == "cross.plan_vs_shop"
        and f.plan_ref
        and f.shop_ref
        and not f.evidence.rule.fired
    ]
    if len(agreeing) < MIN_PAIRS_TO_LEARN:
        return findings
    X, y = build_dataset_from_bundle(bundle)
    if len(set(y)) < 2:
        return findings
    model = pair_model.train(X, y)
    out: list[Finding] = []
    for f in findings:
        if f.check_type != "cross.plan_vs_shop" or not (f.plan_ref and f.shop_ref):
            out.append(f)
            continue
        prob = model.predict(f)
        fired = f.evidence.rule.fired
        status = f.status
        if not fired and status == C.STATUS_COMPLIANT:
            status = fusion.decide_pair(False, f.trust, None, prob)
        discrepancy = fusion.discrepancy_probability(fired, prob)
        conforming = not fired and status == C.STATUS_COMPLIANT
        ml = MlEvidence(pair_probability=round(prob, 3), model_version=model.version)
        out.append(
            f.model_copy(
                update={
                    "status": status,
                    "discrepancy_probability": discrepancy,
                    "confidence": fusion.confidence(f.trust, discrepancy, conforming),
                    "evidence": f.evidence.model_copy(update={"ml": ml}),
                }
            )
        )
    return out


def run_comparison(bundle: MetaBundle, use_ml: bool = False) -> list[Finding]:
    plan = [e for e in bundle.elements if e.source == "plan"]
    shop = [e for e in bundle.elements if e.source == "shop"]
    plan_levels = {e.level for e in plan}
    shop_levels = {e.level for e in shop}
    findings: list[Finding] = [compare_pair(p, plan_levels, shop_levels) for p in match(plan, shop)]
    if use_ml:
        findings = add_pair_probabilities(findings, bundle)
    findings += [outlier_finding(o) for o in peer_outliers(bundle.elements)]
    findings += internal_consistency_findings(bundle.elements, bundle.levels)
    findings += plausibility_findings(bundle.elements)
    findings += duplicate_findings(bundle.elements)
    return sorted(findings, key=lambda f: (f.level, f.grid or "", f.check_type, f.id))
