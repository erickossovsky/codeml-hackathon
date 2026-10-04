"""Local-only checks of the extractor on a real project. Prints counts and percentages only.

Usage: python scripts/validate_extract.py <project_dir>
Exit code 1 when a MVP threshold is missed (spec 10.16 criteria 3 and 4).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from l2c.compare.run import run_comparison
from l2c.contract import constants as C
from l2c.extract.calibrate import calibrate
from l2c.extract.columns_plan import assemble_blocks, extract_plan_columns
from l2c.extract.columns_shop import extract_shop_columns
from l2c.extract.grid import fit_grid
from l2c.extract.notation import plan_column_level
from l2c.extract.pipeline import discover, extract_project
from l2c.ingest.pages import load_pdf

PLAN_BOUND_MIN = 0.90
PLAN_PARSED_MIN = 0.95
SHOP_PARSED_MIN = 0.90


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", type=Path)
    args = ap.parse_args()
    found = discover(args.project_dir)
    ok = True
    print("PLAN column sheets: file page level blocks parsed% bound%")
    for pdf_no, pdf in enumerate(found.plans, 1):
        for page in load_pdf(pdf, pdf.name):
            level = plan_column_level(" ".join(w.text for w in page.words))
            if not level:
                continue
            census = len(assemble_blocks(page, scale=calibrate(page.words)))
            els = extract_plan_columns(page, level, fit_grid(page.words))
            parsed = sum(e.armature[0].quantite is not None for e in els)
            bound = sum(e.grid is not None for e in els)
            pp, bb = parsed / max(census, 1), bound / max(census, 1)
            flag = "" if pp >= PLAN_PARSED_MIN and bb >= PLAN_BOUND_MIN else "  <-- below threshold"
            ok &= not flag
            print(f"  plan file #{pdf_no} p{page.page} {level} {census} {pp:.0%} {bb:.0%}{flag}")
    print("SHOP column files: file page vert-runs elements parsed%  (file numbers, no names)")
    for shop_no, (pdf, etype) in enumerate(found.shops, 1):
        if etype != "colonne":
            continue
        for page in load_pdf(pdf, pdf.name):
            if len(page.words) < 10:
                continue
            census = sum(1 for w in page.words if w.text.upper().startswith("VERT:"))
            els, _ = extract_shop_columns(page)
            if census == 0:
                continue
            pp = len(els) / census
            flag = "" if pp >= SHOP_PARSED_MIN else "  <-- below threshold"
            ok &= not flag
            print(f"  shop file #{shop_no} p{page.page} {census} {len(els)} {pp:.0%}{flag}")
    print("ALL TYPES: type sheets elements failed-pages | plan-shop pairs: compliant non_compliant needs_review")
    bundle = extract_project(args.project_dir)
    findings = run_comparison(bundle)
    for t in C.ELEMENT_TYPES:
        sheets = [s for s in bundle.sheets if s.type_element == t]
        n_el = sum(1 for e in bundle.elements if e.type_element == t)
        failed = sum(1 for s in sheets if s.layout.startswith("error"))
        pairs = Counter(f.status for f in findings if f.type_element == t and f.plan_ref and f.shop_ref)
        flag = ""
        if sheets and n_el == 0:
            flag = "  <-- sheets found, no elements"
        elif failed:
            flag = "  <-- pages failed"
        ok &= not flag
        print(
            f"  {t} {len(sheets)} {n_el} {failed} | {pairs[C.STATUS_COMPLIANT]} "
            f"{pairs[C.STATUS_NON_COMPLIANT]} {pairs[C.STATUS_NEEDS_REVIEW]}{flag}"
        )
    print("RESULT:", "pass" if ok else "below threshold")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
