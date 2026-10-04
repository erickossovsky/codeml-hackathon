"""Checks of one metadata file against itself: peer outliers, internal consistency, plausibility."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

from l2c.compare import fusion
from l2c.compare.cross import finding_id, ref
from l2c.compare.profile import profile
from l2c.contract import constants as C
from l2c.contract.models import (
    Diff,
    ElementExt,
    Evidence,
    ExtractionEvidence,
    Finding,
    LevelInfo,
    MlEvidence,
    RuleEvidence,
)

PEER_FIELDS = ("count", "size", "tie_size", "spacing_mm")


@dataclass(frozen=True)
class Outlier:
    element: ElementExt
    field: str
    value: float | int | str
    mode: float | int | str
    score: float


def peer_outliers(elements: list[ElementExt]) -> list[Outlier]:
    """Elements with a value rare among peers (same sheet and level) when the peers agree."""
    groups: dict[tuple[str, str, int, str], list[ElementExt]] = {}
    for e in elements:
        groups.setdefault((e.source, e.fichier, e.page, e.level), []).append(e)
    found: list[Outlier] = []
    for _, members in sorted(groups.items()):
        if len(members) < C.PEER_MIN_GROUP:
            continue
        for field in PEER_FIELDS:
            values = [(e, getattr(profile(e), field)) for e in members]
            values = [(e, v) for e, v in values if v is not None]
            if len(values) < C.PEER_MIN_GROUP:
                continue
            counts = Counter(v for _, v in values)
            mode, mode_n = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[0]
            mode_share = mode_n / len(values)
            if mode_share < C.PEER_MODE_SHARE_MIN:
                continue
            for e, v in values:
                share = counts[v] / len(values)
                if v != mode and share <= C.PEER_RARE_SHARE_MAX:
                    found.append(Outlier(e, field, v, mode, round(mode_share * (1 - share), 3)))
    return sorted(found, key=lambda o: (o.element.id, o.field))


def outlier_finding(o: Outlier) -> Finding:
    e = o.element
    t = e.quality.overall
    return Finding(
        id=finding_id("self.peer_outlier", e.id, o.field),
        check_type="self.peer_outlier",
        status=C.STATUS_NEEDS_REVIEW,  # type: ignore[arg-type]
        type_element=e.match_key.type,
        level=e.level,
        grid=e.grid,
        plan_ref=ref(e) if e.source == "plan" else None,
        shop_ref=ref(e) if e.source == "shop" else None,
        diffs=[Diff(field=f"{o.field} (value vs peer mode)", plan=o.value, shop=o.mode)],
        evidence=Evidence(
            rule=RuleEvidence(fired=False, kind="peer_outlier"),
            extraction=ExtractionEvidence(
                plan_overall=t if e.source == "plan" else None,
                shop_overall=t if e.source == "shop" else None,
                flags=list(e.quality.flags),
            ),
            ml=MlEvidence(peer_anomaly=o.score, model_version="mode-share-v1"),
        ),
        trust=t,
        discrepancy_probability=o.score,
        confidence=fusion.confidence(t, o.score, conforming=False),
        notes=f"{o.field} differs from {o.mode!r} used by most peers on this sheet",
    )


def storey_heights(levels: list[LevelInfo]) -> dict[str, float]:
    ordered = sorted(
        (lv for lv in levels if lv.elevation_mm is not None), key=lambda lv: lv.elevation_mm or 0.0
    )
    return {
        lo.level: (hi.elevation_mm or 0.0) - (lo.elevation_mm or 0.0)
        for lo, hi in zip(ordered, ordered[1:], strict=False)
    }


def tie_ratios(elements: list[ElementExt], heights: dict[str, float]) -> dict[str, float]:
    """tie count x spacing / storey height for every shop element that has all three."""
    out: dict[str, float] = {}
    for e in elements:
        if e.source != "shop":
            continue
        p = profile(e)
        h = heights.get(e.level)
        if h and p.tie_count is not None and p.spacing_mm is not None:
            out[e.id] = round(p.tie_count * p.spacing_mm / h, 3)
    return out


def learned_band(ratios: list[float]) -> tuple[float, float, str]:
    """Accepted ratio band from the project's own data; fixed fallback when too few samples."""
    if len(ratios) < C.TIE_BAND_MIN_SAMPLES:
        return C.TIE_RATIO_MIN, C.TIE_RATIO_MAX, "fallback"
    med = statistics.median(ratios)
    mad = statistics.median(abs(r - med) for r in ratios)
    sigma = max(1.4826 * mad, C.TIE_BAND_SIGMA_FLOOR * med)
    return med - C.TIE_BAND_K * sigma, med + C.TIE_BAND_K * sigma, "learned"


def internal_consistency_findings(
    elements: list[ElementExt], levels: list[LevelInfo]
) -> list[Finding]:
    """Ties are spread over the storey: tie count x spacing is about the storey height."""
    ratios = tie_ratios(elements, storey_heights(levels))
    if not ratios:
        return []
    lo, hi, how = learned_band(list(ratios.values()))
    by_id = {e.id: e for e in elements}
    out: list[Finding] = []
    for element_id, ratio in sorted(ratios.items()):
        if lo <= ratio <= hi:
            continue
        e = by_id[element_id]
        t = e.quality.overall
        out.append(
            Finding(
                id=finding_id("self.internal_consistency", e.id),
                check_type="self.internal_consistency",
                status=C.STATUS_NEEDS_REVIEW,  # type: ignore[arg-type]
                type_element=e.match_key.type,
                level=e.level,
                grid=e.grid,
                shop_ref=ref(e),
                diffs=[
                    Diff(
                        field="tie_count*spacing/height",
                        plan=f"{lo:.2f}-{hi:.2f} ({how} band)",
                        shop=ratio,
                    )
                ],
                evidence=Evidence(
                    rule=RuleEvidence(fired=True, kind="internal_consistency"),
                    extraction=ExtractionEvidence(shop_overall=t, flags=list(e.quality.flags)),
                ),
                trust=t,
                discrepancy_probability=1.0,
                confidence=fusion.confidence(t, 1.0, conforming=False),
                notes="tie count and spacing do not fit the storey height",
            )
        )
    return out


def plausibility_findings(elements: list[ElementExt]) -> list[Finding]:
    out: list[Finding] = []
    for e in elements:
        failed = e.quality.consistency_failed
        if not failed:
            continue
        t = e.quality.overall
        out.append(
            Finding(
                id=finding_id("self.plausibility", e.id),
                check_type="self.plausibility",
                status=C.STATUS_NEEDS_REVIEW,  # type: ignore[arg-type]
                type_element=e.match_key.type,
                level=e.level,
                grid=e.grid,
                plan_ref=ref(e) if e.source == "plan" else None,
                shop_ref=ref(e) if e.source == "shop" else None,
                evidence=Evidence(
                    rule=RuleEvidence(fired=True, kind="plausibility"),
                    extraction=ExtractionEvidence(
                        plan_overall=t if e.source == "plan" else None,
                        shop_overall=t if e.source == "shop" else None,
                        flags=list(failed),
                    ),
                ),
                trust=t,
                discrepancy_probability=1.0,
                confidence=fusion.confidence(t, 1.0, conforming=False),
                notes="failed sanity checks: " + ", ".join(failed),
            )
        )
    return out
