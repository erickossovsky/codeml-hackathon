"""Block confidential data and secrets from entering git (spec 10.21). Pure Python, any OS.

Used by .githooks/pre-commit and scripts/check.py. `check_paths` is pure so it can be tested.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

BLOCKED_SUFFIXES = {
    ".pdf",
    ".dxf",
    ".dwg",
    ".ifc",
    ".bcf",
    ".bcfzip",
    ".xlsx",
    ".xls",
    ".zip",
    ".onnx",
    ".pt",
    ".pth",
    ".joblib",
    ".pkl",
    ".parquet",
    ".sqlite",
    ".db",
}
BLOCKED_DIRS = {"data", "deliverables", "demo"}
BLOCKED_PREFIXES = ("docs/private/", "metrics/gold/")  # local analysis notes and hand labels
ALLOWED_PREFIXES = ("shared/fixtures/",)  # synthetic, hand-made files only
MAX_BYTES = 1_000_000
SECRET_SCAN_EXEMPT = {"backend/tests/tooling/test_guard.py"}  # holds fake secrets on purpose
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)(?:api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"
    ),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
]


def check_paths(files: dict[str, int], notebook_with_outputs: set[str] | None = None) -> list[str]:
    """`files` maps a repo-relative posix path to its size in bytes."""
    problems: list[str] = []
    for path, size in sorted(files.items()):
        pp = PurePosixPath(path)
        if path.startswith(ALLOWED_PREFIXES):
            if size > MAX_BYTES:
                problems.append(f"{path}: fixture larger than {MAX_BYTES} bytes")
            continue
        if path.startswith(BLOCKED_PREFIXES):
            problems.append(f"{path}: local-only analysis notes and labels are never committed")
        if pp.parts and pp.parts[0] in BLOCKED_DIRS and pp.name != ".gitkeep":
            problems.append(f"{path}: files under {pp.parts[0]}/ must never be committed")
        if pp.suffix.lower() in BLOCKED_SUFFIXES:
            problems.append(f"{path}: {pp.suffix} files may hold confidential data or binaries")
        if size > MAX_BYTES:
            problems.append(f"{path}: {size} bytes exceeds the {MAX_BYTES} byte limit")
    for path in sorted(notebook_with_outputs or set()):
        problems.append(f"{path}: notebook has outputs; strip them before committing")
    return problems


def find_secrets(path: str, text: str) -> list[str]:
    return [
        f"{path}: looks like a secret ({p.pattern[:24]}...)"
        for p in SECRET_PATTERNS
        if p.search(text)
    ]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def staged_files() -> dict[str, int]:
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    files: dict[str, int] = {}
    for name in filter(None, out.split("\0")):
        size = int(_git("cat-file", "-s", f":{name}").strip())
        files[name] = size
    return files


def staged_text(name: str) -> str:
    return subprocess.run(
        ["git", "show", f":{name}"], capture_output=True, check=True
    ).stdout.decode("utf-8", errors="ignore")


def notebooks_with_outputs(names: list[str]) -> set[str]:
    import json

    bad = set()
    for n in names:
        if not n.endswith(".ipynb"):
            continue
        try:
            nb = json.loads(staged_text(n))
        except ValueError:
            continue
        if any(c.get("outputs") for c in nb.get("cells", [])):
            bad.add(n)
    return bad


def main() -> int:
    files = staged_files()
    problems = check_paths(files, notebooks_with_outputs(list(files)))
    for name in files:
        if name in SECRET_SCAN_EXEMPT:
            continue
        if name.endswith((".py", ".json", ".md", ".txt", ".toml", ".yml", ".yaml", ".env", ".cfg")):
            problems += find_secrets(name, staged_text(name))
    if problems:
        print("COMMIT BLOCKED by scripts/guard.py:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("Confidential files never go to git. See spec section 10.21.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
