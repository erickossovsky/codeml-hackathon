"""Aggregate performance report for a comparison run (counts and percentages only, no values).

Usage:
  python scripts/performance_report.py <metadata_dir> <out_dir>
Writes <out_dir>/performance_report.md. Run `python -m l2c.compare` first for the same out_dir.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from pathlib import Path

from l2c.compare.run import run_comparison
from l2c.contract.io import read_bundle
from l2c.match.matcher import match


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def table(title: str, counter: Counter, total: int) -> list[str]:
    lines = [f"### {title}", "", "| item | count | share |", "|---|---:|---:|"]
    lines += [f"| {k} | {v} | {pct(v, total)} |" for k, v in counter.most_common()]
    return [*lines, ""]


def build(meta: Path) -> str:
    bundle = read_bundle(meta)
    t0 = time.perf_counter()
    findings = run_comparison(bundle)
    seconds = time.perf_counter() - t0
    plan = [e for e in bundle.elements if e.source == "plan"]
    shop = [e for e in bundle.elements if e.source == "shop"]
    pairs = match(plan, shop)
    cross = [f for f in findings if f.check_type == "cross.plan_vs_shop"]
    both = [f for f in cross if f.plan_ref and f.shop_ref]
    n = len(findings)

    out = ["# Comparison performance report (aggregates only)", ""]
    out += [
        f"- elements: {len(bundle.elements)} (plan {len(plan)}, shop {len(shop)})",
        f"- shop files: {len({e.fichier for e in shop})}, plan sheets: "
        f"{len({e.feuillet for e in plan})}, levels: {len({e.level for e in bundle.elements})}",
        f"- comparison time: {seconds:.2f}s for {n} findings",
        "",
        "## Findings",
        "",
    ]
    out += table("by status (all checks)", Counter(f.status for f in findings), n)
    out += table("by check type", Counter(f.check_type for f in findings), n)
    out += table("cross.plan_vs_shop by status", Counter(f.status for f in cross), len(cross))

    out += ["## Matching", ""]
    out += table("match method over pairs", Counter(p.method for p in pairs), len(pairs))
    matched = sum(1 for p in pairs if p.plan and p.shop)
    bound_plan = sum(1 for e in plan if e.match_key.row is not None and e.match_key.col is not None)
    out += [
        f"- plan elements with a grid cell: {bound_plan}/{len(plan)} ({pct(bound_plan, len(plan))})",
        f"- plan elements matched to a shop element: {matched}/{len(plan)} "
        f"({pct(matched, len(plan))})",
        f"- shop elements unmatched (`added` candidates): "
        f"{sum(1 for p in pairs if p.shop and not p.plan)}",
        "",
    ]

    out += ["## Verdict quality", ""]
    firm = [f for f in both if f.status in ("compliant", "non_compliant")]
    out += [
        f"- matched pairs with a firm verdict (trust >= 0.7): {len(firm)}/{len(both)} "
        f"({pct(len(firm), len(both))})",
        f"- matched pairs with a rule difference: {sum(f.evidence.rule.fired for f in both)}"
        f" ({pct(sum(f.evidence.rule.fired for f in both), len(both))})",
        f"- of rule differences, firm `non_compliant`: "
        f"{sum(f.status == 'non_compliant' for f in both)}, held back as `needs_review` "
        f"(low trust): {sum(f.evidence.rule.fired and f.status == 'needs_review' for f in both)}",
    ]
    trusts = [f.trust for f in both]
    if trusts:
        qs = statistics.quantiles(trusts, n=4)
        out.append(
            f"- trust of matched pairs: min {min(trusts):.2f}, quartiles "
            f"{qs[0]:.2f}/{qs[1]:.2f}/{qs[2]:.2f}, max {max(trusts):.2f}"
        )
    fields = Counter(d.field for f in both for d in f.diffs)
    out += ["", *table("differing fields in matched pairs", fields, sum(fields.values()))]

    out += ["## Extraction quality (Eric's lane)", ""]
    overall = [e.quality.overall for e in bundle.elements]
    if overall:
        qs = statistics.quantiles(overall, n=4)
        out.append(
            f"- overall quality: min {min(overall):.2f}, quartiles "
            f"{qs[0]:.2f}/{qs[1]:.2f}/{qs[2]:.2f}, max {max(overall):.2f}; "
            f">= 0.7: {pct(sum(o >= 0.7 for o in overall), len(overall))}"
        )
    out.append("")
    out += table(
        "elements by type and source",
        Counter(f"{e.type_element}/{e.source}" for e in bundle.elements),
        len(bundle.elements),
    )
    out += table(
        "failed consistency checks",
        Counter(c for e in bundle.elements for c in e.quality.consistency_failed),
        len(bundle.elements),
    )
    out += table(
        "quality flags",
        Counter(f for e in bundle.elements for f in e.quality.flags),
        len(bundle.elements),
    )

    out += ["## Per level (cross.plan_vs_shop)", ""]
    out += ["| level | plan | shop | compliant | non_compliant | missing | added | needs_review |"]
    out += ["|---|---:|---:|---:|---:|---:|---:|---:|"]
    for lv in sorted({e.level for e in bundle.elements}):
        c = Counter(f.status for f in cross if f.level == lv)
        out.append(
            f"| {lv} | {sum(e.level == lv for e in plan)} | {sum(e.level == lv for e in shop)} | "
            f"{c['compliant']} | {c['non_compliant']} | {c['missing']} | {c['added']} | "
            f"{c['needs_review']} |"
        )
    out += [
        "",
        "## Accuracy",
        "",
        "Not measurable here: precision and recall need the known-discrepancy list as ground "
        "truth, which is not in this run. Shares above describe how findings are distributed, "
        "not how many are correct.",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    args = ap.parse_args()
    text = build(args.metadata_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "performance_report.md").write_text(text, encoding="utf-8", newline="\n")
    (args.out_dir / "performance_report.json").write_text(
        json.dumps({"report": "see performance_report.md"}), encoding="utf-8"
    )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
