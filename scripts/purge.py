"""End-of-event cleanup of confidential data. Dry run unless `--yes` is given.

Removes data/, deliverables/, demo/, metrics/gold/, caches and virtual environments inside the
repository, plus any extra paths passed with --also (for example the original zip and any
extracted copies). Then verifies that none of the removed paths remain.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_TARGETS = [
    "data",
    "deliverables",
    "demo",
    "metrics/gold",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
]


def collect(also: list[Path]) -> list[Path]:
    found = [ROOT / t for t in REPO_TARGETS if (ROOT / t).exists()]
    found += [p for p in also if p.exists()]
    return found


def remove(path: Path) -> None:
    if path.is_dir():
        for child in path.iterdir():
            if child.name == ".gitkeep":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    else:
        path.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    ap.add_argument("--also", type=Path, action="append", default=[], help="extra path to delete")
    args = ap.parse_args()
    targets = collect(args.also)
    for t in targets:
        print(("DELETE " if args.yes else "would delete ") + str(t))
    if not args.yes:
        print("dry run: nothing deleted. Re-run with --yes.")
        return 0
    for t in targets:
        remove(t)
    left = [
        t
        for t in targets
        if t.exists() and (t.is_file() or any(c.name != ".gitkeep" for c in t.iterdir()))
    ]
    print("VERIFIED CLEAN" if not left else f"STILL PRESENT: {left}")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
