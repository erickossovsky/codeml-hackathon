"""Everything that must pass before merging to dev: lint, format check, tests, data guard."""

from __future__ import annotations

import subprocess
import sys


def run(*cmd: str) -> bool:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=False).returncode == 0


def main() -> int:
    py = sys.executable
    steps = [
        (py, "-m", "ruff", "check", "backend", "scripts"),
        (py, "-m", "ruff", "format", "--check", "backend", "scripts"),
        (py, "-m", "pytest"),
        (py, "scripts/guard.py"),
    ]
    ok = all([run(*s) for s in steps])
    print("CHECK", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
