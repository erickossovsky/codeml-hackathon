"""First command to run on an unseen project: what will the extractor cover, and why not the rest?

Prints counts only (never drawing text). Local use.
Usage: python scripts/probe_project.py <project_dir> [--config overrides.json]
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from l2c.extract.config import load_config
from l2c.extract.pipeline import discover, extract_project

ADVICE = {
    "needs_ocr": "no text layer: needs the OCR path (SECOND tier)",
    "shop_unlabelled_unsupported": "column blocks without grid labels: needs the mark+axis adapter",
    "plan_blocks_without_grid": "blocks found but no grid: elements will be unbound (needs_review)",
    "rotated_text_unsupported": "text drawn sideways: not supported yet",
    "no_column_blocks": "shop page without column blocks (details, notes?)",
    "shop_levels_not_found": "blocks and labels but no elevation lines: no level can be assigned",
    "not_a_column_plan": "plan page that is not a column plan (other element type or notes)",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()
    found = discover(args.project_dir)
    print(f"plan pdfs: {len(found.plans)}   shop pdfs: {len(found.shops)}")
    bundle = extract_project(args.project_dir, config=load_config(args.config))
    for kind in ("plan", "shop"):
        layouts = Counter(s.layout for s in bundle.sheets if s.kind == kind)
        print(f"\n{kind} pages by layout ({sum(layouts.values())} pages):")
        for name, n in sorted(layouts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {name}" + (f"   <- {ADVICE[name]}" if name in ADVICE else ""))
    layers = Counter((s.kind, s.layer) for s in bundle.sheets)
    print("\nlayer kinds:", {f"{k}/{v}": n for (k, v), n in sorted(layers.items())})
    plan = sum(e.source == "plan" for e in bundle.elements)
    shop = sum(e.source == "shop" for e in bundle.elements)
    flags = Counter(f for e in bundle.elements for f in e.quality.flags)
    print(f"\nelements: plan={plan} shop={shop}   levels={[lv.level for lv in bundle.levels]}")
    print("quality flags:", dict(flags.most_common(6)))
    covered = sum(
        1
        for s in bundle.sheets
        if s.layout in {"plan_outline", "shop_label_strip", "shop_schedule_table"}
    )
    print(f"pages fully handled: {covered} of {len(bundle.sheets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
