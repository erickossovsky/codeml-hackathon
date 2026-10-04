"""Feedback for the extraction lane: what the comparison learned about the metadata quality.

Usage: python scripts/metadata_feedback.py <metadata_dir> <out_dir>
Writes <out_dir>/metadata_feedback.md. Aggregates only (counts, ratios, level names); no drawing
text. The file is generated from confidential data: send it out of band, never commit it.
"""

from __future__ import annotations

import argparse
import copy
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from l2c.compare.profile import profile, profile_diffs
from l2c.compare.run import run_comparison
from l2c.contract.io import read_bundle
from l2c.match.matcher import match

INCH = 25.4


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def what_if(b) -> list[str]:
    """Re-run the comparison in memory with plan spacings divided by 25.4 (nothing is written)."""
    fixed = b.model_copy(deep=True) if hasattr(b, "model_copy") else copy.deepcopy(b)
    for e in fixed.elements:
        if e.source == "plan":
            for a in e.armature:
                if a.espacement_mm:
                    a.espacement_mm = round(a.espacement_mm / INCH, 1)
            e.quality.consistency_failed = [
                c for c in e.quality.consistency_failed if c != "spacing_plausible"
            ]
    before = Counter(f.status for f in run_comparison(b) if f.check_type == "cross.plan_vs_shop")
    after = Counter(f.status for f in run_comparison(fixed) if f.check_type == "cross.plan_vs_shop")
    return [
        "- what-if (plan spacing / 25.4, in memory only), plan-vs-shop statuses:",
        f"  - now:   {dict(before)}",
        f"  - fixed: {dict(after)}",
    ]


def build(meta: Path) -> str:
    b = read_bundle(meta)
    plan = [e for e in b.elements if e.source == "plan"]
    shop = [e for e in b.elements if e.source == "shop"]
    pairs = [p for p in match(plan, shop) if p.plan and p.shop]
    out = ["# Metadata feedback for the extraction lane", ""]
    n = 0

    # 1. spacing unit
    ratios = [
        profile(p.shop).spacing_mm / profile(p.plan).spacing_mm
        for p in pairs
        if profile(p.shop).spacing_mm and profile(p.plan).spacing_mm
    ]
    out += ["## 1. Tie spacing unit", ""]
    if ratios:
        med = statistics.median(ratios)
        out.append(
            f"- median shop/plan spacing ratio over {len(ratios)} matched pairs: {med:.4f} "
            f"(1/25.4 = {1 / INCH:.4f})"
        )
        if abs(med * INCH - 1) < 0.1:
            n += 1
            out.append(
                "- **Likely unit error on the plan side**: plan spacings are ~25.4x the shop "
                "spacings, i.e. a value written in mm was multiplied by 25.4 as if inches. "
                "Detect the unit per document instead of assuming `default_spacing_unit`."
            )
            out += what_if(b)
        elif abs(med - 1) < 0.1:
            out.append("- units agree.")
    plaus = Counter((e.source, c) for e in b.elements for c in e.quality.consistency_failed)
    out += [
        f"- failed consistency checks by (source, check): {dict(plaus)}",
        "- A systematic unit error makes the comparison report most pairs as non_compliant; "
        "fix this first, then re-run.",
        "",
    ]

    # 2. duplicates
    out += ["## 2. Same element extracted more than once", ""]
    for source, els in (("plan", plan), ("shop", shop)):
        groups: dict[str, list] = defaultdict(list)
        for e in els:
            if e.match_key.row is not None and e.match_key.col is not None:
                groups[e.match_key.key_str()].append(e)
        dups = {k: v for k, v in groups.items() if len(v) > 1}
        conflicting = sum(
            any(profile_diffs(profile(v[0]), profile(o)) for o in v[1:]) for v in dups.values()
        )
        out.append(
            f"- {source}: {len(dups)} match keys have several elements "
            f"({sum(len(v) for v in dups.values())} elements), {conflicting} with conflicting "
            f"values. Identical repeats are harmless but check the key is really unique "
            f"(level, row, column, plus sheet if the same column appears on several sheets)."
        )
    out.append("")

    # 3. coverage by level
    pl, sl = {e.level for e in plan}, {e.level for e in shop}
    out += [
        "## 3. Level coverage",
        "",
        f"- levels with plan elements but no shop elements: {sorted(pl - sl)}",
        f"- levels with shop elements but no plan elements: {sorted(sl - pl)}",
        "- Check these are real coverage gaps and not level-name normalisation differences "
        "(for example a shop file whose level range was not parsed).",
        "",
    ]

    # 4. binding and quality
    unbound = [e for e in b.elements if e.match_key.row is None or e.match_key.col is None]
    overall = [e.quality.overall for e in b.elements]
    out += [
        "## 4. Binding and quality",
        "",
        f"- elements without a grid cell: {len(unbound)} ({pct(len(unbound), len(b.elements))})",
        f"- elements with overall quality < 0.7: "
        f"{sum(o < 0.7 for o in overall)} ({pct(sum(o < 0.7 for o in overall), len(overall))})",
        "- most common flags: "
        + str(Counter(f for e in b.elements for f in e.quality.flags).most_common(8)),
        "",
    ]
    ties_missing = sum(
        1 for e in shop if profile(e).tie_count is None and profile(e).spacing_mm is not None
    )
    out += [
        "## 5. Fields the comparison needs",
        "",
        f"- shop elements without a tie count: {ties_missing}/{len(shop)} (the storey-height "
        "consistency check needs tie count x spacing)",
        f"- elements typed only as colonne: {Counter(e.type_element for e in b.elements)}; "
        "other element types are reported as NOT COVERED",
        "",
        f"Automatic detection flagged {n} systematic issue(s) above.",
    ]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    text = build(args.metadata_dir)
    (args.out_dir / "metadata_feedback.md").write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
