"""The whole MVP flow in one command: PDFs -> metadata -> findings, comparison files and reports.

Usage: python scripts/run_flow.py <project_dir> [--out data/out/<name>] [--ocr] [--workers N]
Writes <out>/metadata (extraction) and <out>/compare (findings, per-shop files, PDFs, XLSX).
Prints counts and timings only, never drawing values.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from l2c.compare.__main__ import main as compare_main
from l2c.extract.__main__ import main as extract_main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--ocr", action="store_true", help="read pages without a text layer")
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()
    out = args.out or Path("data/out") / args.project_dir.name
    t0 = time.time()
    extract_args = [str(args.project_dir), "--out", str(out / "metadata")]
    extract_args += ["--workers", str(args.workers)]
    if args.ocr:
        extract_args.append("--ocr")
    code = extract_main(extract_args)
    if code:
        return code
    t1 = time.time()
    code = compare_main([str(out / "metadata"), "--out", str(out / "compare")])
    print(f"extract {t1 - t0:.1f}s, compare {time.time() - t1:.1f}s, output in {out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
