"""Summarise a findings.json (local use; may print values when you ask for one cell).

Usage:
  python scripts/findings_summary.py data/out/<project>/findings.json
  python scripts/findings_summary.py data/out/<project>/findings.json --grid D-6 --level N2
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def summarise(findings: list[dict]) -> str:
    by_status = Counter(f["status"] for f in findings)
    by_check = Counter((f["check_type"], f["status"]) for f in findings)
    lines = [f"{len(findings)} findings", "by status: " + str(dict(sorted(by_status.items())))]
    lines += [f"  {check:<28} {status:<14} {n}" for (check, status), n in sorted(by_check.items())]
    return "\n".join(lines)


def show_cell(findings: list[dict], grid: str, level: str | None) -> str:
    rows = []
    for f in findings:
        if f["grid"] != grid or (level and f["level"] != level):
            continue
        diffs = "; ".join(f"{d['field']}: plan {d['plan']} / shop {d['shop']}" for d in f["diffs"])
        rows.append(
            f"{f['level']:>4} {f['grid']:<7} {f['check_type']:<26} {f['status']:<13} "
            f"trust {f['trust']:.2f} conf {f['confidence']:.2f}  {diffs or '-'}"
        )
    return "\n".join(rows) or "no finding for that cell"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("findings", type=Path)
    ap.add_argument("--grid")
    ap.add_argument("--level")
    args = ap.parse_args()
    data = json.loads(args.findings.read_text(encoding="utf-8"))
    print(show_cell(data, args.grid, args.level) if args.grid else summarise(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
