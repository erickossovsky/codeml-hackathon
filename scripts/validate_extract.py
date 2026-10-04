"""Local-only checks of the extractor on a real project. Prints counts and percentages only.

Usage: python scripts/validate_extract.py <project_dir>
Exit code 1 when a MVP threshold is missed (spec 10.16 criteria 3 and 4).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from l2c.extract.calibrate import calibrate
from l2c.extract.columns_plan import assemble_blocks, extract_plan_columns
from l2c.extract.columns_shop import extract_shop_columns
from l2c.extract.grid import fit_grid
from l2c.extract.notation import plan_column_level
from l2c.extract.pipeline import discover
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
    print("PLAN column sheets: sheet level blocks parsed% bound%")
    for pdf in found.plans:
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
            print(f"  {page.feuillet} {level} {census} {pp:.0%} {bb:.0%}{flag}")
    print("SHOP column files: file page vert-runs elements parsed%")
    for pdf, etype in found.shops:
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
            print(f"  {pdf.name[-18:]} p{page.page} {census} {len(els)} {pp:.0%}{flag}")
    print("RESULT:", "pass" if ok else "below threshold")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
