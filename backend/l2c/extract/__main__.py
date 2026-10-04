"""`python -m l2c.extract <project_dir> --out <dir>`: write the metadata bundle for a project."""

from __future__ import annotations

import argparse
import os
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
    ap.add_argument(
        "--workers",
        type=int,
        default=0,
        help="worker processes for page reading and OCR (default: cores - 1; 1 = sequential)",
    )
    ap.add_argument(
        "--ocr-cache",
        type=Path,
        default=Path("data/cache/ocr"),
        help="folder where OCR readings are kept so a page is read once (default: data/cache/ocr)",
    )
    ap.add_argument(
        "--ocr-workers",
        type=int,
        default=1,
        help="OCR worker processes (default 1: measured no faster in parallel)",
    )
    ap.add_argument("--no-ocr-cache", action="store_true", help="read every page again")
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
        workers=args.workers or max(1, (os.cpu_count() or 2) - 1),
        ocr_cache=None if args.no_ocr_cache else args.ocr_cache,
        ocr_workers=args.ocr_workers,
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
    code = main()
    # Everything is written and closed. Leave at once: the ONNX runtime can abort in its native
    # shutdown code after OCR, which would turn a finished run into a failing exit code.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
