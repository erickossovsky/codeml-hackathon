"""The same element annotated twice with different values (across shop files, or on one sheet)."""

from __future__ import annotations

from l2c.compare import fusion
from l2c.compare.cross import finding_id, ref
from l2c.compare.profile import profile, profile_diffs
from l2c.contract import constants as C
from l2c.contract.models import ElementExt, Evidence, ExtractionEvidence, Finding, RuleEvidence


def duplicate_findings(elements: list[ElementExt]) -> list[Finding]:
    groups: dict[tuple[str, str], list[ElementExt]] = {}
    for e in elements:
        k = e.match_key
        if k.row is None or k.col is None:
            continue
        groups.setdefault((e.source, k.key_str()), []).append(e)
    out: list[Finding] = []
    for (source, _), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        members.sort(key=lambda e: (e.fichier, e.page, e.id))
        first = members[0]
        for other in members[1:]:
            diffs = profile_diffs(profile(first), profile(other))
            if not diffs:
                continue  # an identical duplicate is harmless
            cross_file = first.fichier != other.fichier
            check = "cross.shop_vs_shop" if (source == "shop" and cross_file) else "self.duplicate"
            t = round(min(first.quality.overall, other.quality.overall), 3)
            out.append(
                Finding(
                    id=finding_id(check, first.id, other.id),
                    check_type=check,  # type: ignore[arg-type]
                    status=C.STATUS_NEEDS_REVIEW,  # type: ignore[arg-type]
                    type_element=first.match_key.type,
                    level=first.level,
                    grid=first.grid,
                    plan_ref=ref(first) if source == "plan" else None,
                    shop_ref=ref(other) if source == "shop" else None,
                    diffs=diffs,
                    evidence=Evidence(
                        rule=RuleEvidence(fired=True, kind="duplicate_conflict", diffs=diffs),
                        extraction=ExtractionEvidence(
                            plan_overall=first.quality.overall if source == "plan" else None,
                            shop_overall=t if source == "shop" else None,
                        ),
                    ),
                    trust=t,
                    discrepancy_probability=1.0,
                    confidence=fusion.confidence(t, 1.0, conforming=False),
                    notes=(
                        f"{first.fichier} p{first.page} and {other.fichier} p{other.page} disagree"
                    ),
                )
            )
    return out
