"""Binding accuracy estimate for a metadata folder, using the shop drawings as a witness.

Usage: python scripts/binding_witness.py data/out/<project>/metadata
Prints percentages only. A binding change must not lower the atypical agreement.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from l2c.contract.io import read_bundle
from l2c.extract.witness import witness


def pct(a: int, b: int) -> str:
    return f"{a}/{b} = {a / b:.0%}" if b else "n/a (no cases)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata_dir", type=Path)
    args = ap.parse_args()
    w = witness(read_bundle(args.metadata_dir))
    typical = pct(w.typical_agree, w.typical_total)
    atypical = pct(w.atypical_agree, w.atypical_total)
    chance = pct(w.chance_agree, w.chance_total)
    print(f"cells present on both plan and shop: {w.matched_cells}")
    print(f"typical plan columns agree with shop at the same cell : {typical}")
    print(f"ATYPICAL plan columns agree with shop (binding estimate): {atypical}")
    print(f"chance level for atypical columns (random cell)        : {chance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
