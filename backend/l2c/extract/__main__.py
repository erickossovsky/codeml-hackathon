"""`python -m l2c.extract <project_dir> --out <dir>`: write the metadata bundle for a project."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from l2c.contract.io import write_bundle
from l2c.extract.config import load_config
from l2c.extract.pipeline import extract_project


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l2c.extract")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--project", default=None)
    ap.add_argument("--ocr", action="store_true", help="read pages without a text layer with OCR")
    ap.add_argument(
        "--no-learn", action="store_true", help="do not learn labels from each page (config only)"
    )
    ap.add_argument(
        "--config",
        type=Path,
        default=None,
        help="JSON overrides for vocabulary, notation and tuning",
    )
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"not a directory: {args.project_dir}", file=sys.stderr)
        return 2
    bundle = extract_project(
        args.project_dir,
        args.project,
        load_config(args.config),
        use_ocr=args.ocr,
        learn=not args.no_learn,
    )
    write_bundle(args.out, bundle)
    flags = Counter(f for e in bundle.elements for f in e.quality.flags)
    layouts = Counter(s.layout for s in bundle.sheets)
    # counts only: never print drawing values
    print(
        f"elements={len(bundle.elements)} "
        f"plan={sum(e.source == 'plan' for e in bundle.elements)} "
        f"shop={sum(e.source == 'shop' for e in bundle.elements)} "
        f"layouts={dict(sorted(layouts.items(), key=lambda kv: str(kv[0])))} "
        f"flags={dict(sorted(flags.items()))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
