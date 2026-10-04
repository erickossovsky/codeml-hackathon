"""Write a local CSV of N random extracted elements so a person can verify them in the PDF.

The CSV holds real values: it is written under data/ (git-ignored) and never shared.
Usage: python scripts/sample_for_handcheck.py <metadata_dir> --n 20 --out data/handcheck.csv
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from l2c.contract.io import read_bundle


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata_dir", type=Path)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    els = read_bundle(args.metadata_dir).elements
    rng = random.Random(args.seed)
    sample = rng.sample(els, min(args.n, len(els)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "id",
                "source",
                "file",
                "page",
                "x",
                "y",
                "grid",
                "level",
                "count",
                "size",
                "tie_spacing_mm",
                "overall",
                "flags",
                "correct? (y/n)",
                "note",
            ]
        )
        for e in sample:
            a = e.armature
            w.writerow(
                [
                    e.id,
                    e.source,
                    e.fichier,
                    e.page,
                    e.x,
                    e.y,
                    e.grid,
                    e.level,
                    a[0].quantite if a else "",
                    a[0].diametre if a else "",
                    next((x.espacement_mm for x in a if x.espacement_mm is not None), ""),
                    e.quality.overall,
                    ";".join(e.quality.flags),
                    "",
                    "",
                ]
            )
    print(f"wrote {len(sample)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
