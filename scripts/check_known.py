"""Check a run against a project's known-discrepancy workbook (sheet, location, plan, shop).

Usage: python scripts/check_known.py <metadata_dir> <workbook.xlsx>
Prints, for each known item, the findings on that sheet and location. Local use only.
Exit code 1 when a known item is not found as non_compliant (or missing/added).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl

from l2c.compare.run import run_comparison
from l2c.contract.io import read_bundle

FOUND = {"non_compliant", "missing", "added"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata_dir", type=Path)
    ap.add_argument("workbook", type=Path)
    args = ap.parse_args()
    bundle = read_bundle(args.metadata_dir)
    byid = {e.id: e for e in bundle.elements}
    findings = run_comparison(bundle)
    rows = [r for r in openpyxl.load_workbook(args.workbook).active.iter_rows(values_only=True)][1:]
    hits = 0
    for sheet, loc, plan_v, shop_v in rows:
        if not sheet:
            continue
        print(f"== {sheet} {loc}: plan {plan_v} | shop {shop_v}")
        matched = []
        for f in findings:
            # the workbook locates items on the plan sheet: match on the plan side of the finding
            if not f.plan_ref:
                continue
            e = byid[f.plan_ref.element_id]
            if e.feuillet != sheet or e.match_key.col is None or f"{e.match_key.row}-{e.match_key.col:g}" != loc:
                continue
            matched.append(f)
            print(f"   {f.status:13} trust {f.trust:.2f} {f.check_type}: "
                  + ", ".join(f"{d.field} {d.plan}->{d.shop}" for d in f.diffs[:3]))
        if any(f.status in FOUND for f in matched):
            hits += 1
        elif not matched:
            print("   no finding at this location")
    print(f"found {hits} of {len(rows)} known items")
    return 0 if hits == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
