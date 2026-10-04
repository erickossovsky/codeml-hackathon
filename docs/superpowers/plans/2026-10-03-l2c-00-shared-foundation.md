# L2C Shared Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give both lanes the same repository scaffold, data/secret guard, metadata contract, committed fixtures and mock-project generator, so Eric (PDF to metadata) and Ian (metadata to comparison) can work in parallel on two computers without waiting for each other.

**Architecture:** One Python package `l2c` under `backend/` with a lane per sub-package. The contract (`l2c.contract`: pydantic models, constants, deterministic JSON I/O) is the only thing both lanes import. JSON Schemas in `shared/schemas/` are generated from the models; synthetic fixtures in `shared/fixtures/mock_a/` are generated from the mock project and are the shared definition of "what the metadata looks like".

**Tech Stack:** Python 3.12, uv, pydantic v2, jsonschema, pytest, ruff. Git hooks written in Python (work on Windows through Git Bash).

**Spec:** `docs/superpowers/specs/2026-10-03-l2c-design.md` (sections 10.9 to 10.11, 10.17 to 10.22).

**Who runs what:** Tasks F1 to F3 are Eric's (about 30 minutes); Task F4 is Ian's (about 40 minutes, after pulling F1 to F3). While Eric does F1 to F3, Ian does Task I0 of his own plan (Windows environment) and reads `docs/superpowers/specs/2026-10-03-l2c-design.md` section 10.19 and 10.22.

## Global Constraints

- Python core, **Python 3.12** managed with `uv`; all code uses `pathlib` and writes text with `newline="\n"` (works on macOS and Windows).
- Output JSON must conform to the provided Appendix A schema: strict `elements.json` records contain exactly `id, source, fichier, feuillet, page, x, y, type_element, element, armature` and nothing else; extras live in `elements.ext.json`.
- Coordinates are PDF points of the page **as displayed** (rotation applied once), origin top-left, y downward; `x, y` is the centre of the annotation.
- Spacings written with a quote mark or bare number are inches (`config.default_spacing_unit`); `mm` is always explicit; stored as `espacement_mm`. Bar sizes come from `config.bar_sizes` (default `10M 15M 20M 25M 30M 35M`).
- `contract_version` is `"0.1.0"`; every metadata folder has a `manifest.json`; loaders fail loudly on a mismatch.
- Same input must give byte-identical output (sorted keys, no randomness without a fixed seed).
- **Nothing is hard-coded to one project**: distances are multiples of the page's own word height or gridline spacing (`calibrate.py`); language, notation, units and ratios live in `Config` and can be overridden with `--config file.json`.
- **Analysis is allowed; hard-coding what analysis finds is not.** Code, tests, fixtures, the spec and the plans contain no project names, sheet ids, grid cells, marks, real values or real notation strings (only published standard forms such as bar sizes `10M`..`35M`). Data-derived numbers and examples live only in the git-ignored `docs/private/` notes, which `scripts/guard.py` refuses to commit. Every behaviour must work on a synthetic document built differently (scale, rotation, language, labels, grid orientation, bar-size system).
- No document may be sent to any cloud service or external AI API; the pipeline imports no network library and runs offline. Confidential data (PDFs, derived JSON/XLSX/PDF outputs, models) is never committed: `data/`, `deliverables/`, `demo/` are git-ignored and `scripts/guard.py` blocks them in the pre-commit hook. Tests use synthetic data only.
- No commercially licensed software; dependencies are open source (PyMuPDF is AGPL-3.0: the source ships with the submission). `THIRD_PARTY.md` lists every dependency and license.
- Each lane edits only its own folders (`.github/CODEOWNERS`); `shared/` and `backend/l2c/contract/` change only through a contract PR reviewed by both people, which also regenerates `shared/schemas/` and `shared/fixtures/` in the same commit.
- Commits: short imperative subject; **no `Co-Authored-By` trailer and no "Generated with" line**. Do not push until Eric lifts the current no-push rule and `git log --all --stat` shows no PDF/XLSX/DXF/IFC/BCF/zip files.

> **Pushing.** The current team rule is *do not push*. Two computers cannot share the contract without a transport, so before Task F1 is shared Eric either (a) lifts the rule for the private repo after running `git log --all --stat | grep -Ei "\.(pdf|xlsx|dxf|ifc|bcf|zip)"` (must print nothing), or (b) uses a git bundle over USB/AirDrop: `git bundle create l2c.bundle dev` on one machine, `git fetch l2c.bundle dev:dev-from-eric` on the other.

## Review Focus

- A teammate changes a model field without regenerating schemas or fixtures: `test_committed_json_schemas_match_the_models` and `test_committed_fixtures_match_the_mock_generator` fail loudly (Tasks F2, F4).
- Someone stages a PDF, an XLSX, a `data/` file, a big file or a notebook with outputs: the pre-commit hook must refuse it and name the file (Task F1).
- A metadata folder written by an older contract is read by newer code: `ContractVersionError` instead of silent wrong data (Task F2).
- The same run twice must give byte-identical JSON, or diffs and golden tests become meaningless (Task F2).
- File names with spaces and accents, and Windows path separators: names inside JSON are always posix paths relative to the project (checked in the extract plan, Task E9).

---

### Task F1: Scaffold, tooling and data guard (Eric)

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `requirements/base.txt`, `requirements/extract.txt`, `requirements/compare.txt`, `requirements/dev.txt`
- Create: `.gitattributes`, `.github/CODEOWNERS`, `.githooks/pre-commit`, `README.md` (replace), `THIRD_PARTY.md`
- Modify: `.gitignore` (append)
- Create: `scripts/guard.py`, `scripts/check.py`, `scripts/install_hooks.py`, `scripts/purge.py`, `scripts/licenses.py`
- Create: `backend/l2c/__init__.py`, `backend/tests/__init__.py`, `backend/tests/tooling/__init__.py`
- Test: `backend/tests/tooling/test_guard.py`

**Interfaces:**
- Produces: `scripts/guard.py:check_paths(files: dict[str, int], notebook_with_outputs: set[str] | None = None) -> list[str]` and `find_secrets(path: str, text: str) -> list[str]` (pure, tested); the importable package `l2c` (editable install); `python scripts/check.py` as the one command that must pass before any merge to `dev`.

- [ ] **Step 1: Start a branch and create the environment**

```bash
git switch dev
git switch -c eric/f1-scaffold
```

macOS / Linux:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e .
```

Windows (PowerShell):

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
uv pip install -e .
```

- [ ] **Step 2: Write the failing guard test**

Create `backend/tests/tooling/test_guard.py`:

```python
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "guard", Path(__file__).resolve().parents[3] / "scripts" / "guard.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_blocks_confidential_file_types_and_data_folders():
    problems = guard.check_paths(
        {
            "docs/plan.pdf": 10,
            "data/out/x/elements.json": 10,
            "deliverables/P/findings.xlsx": 10,
            "backend/l2c/ok.py": 100,
            "data/.gitkeep": 0,
        }
    )
    joined = "\n".join(problems)
    assert "docs/plan.pdf" in joined and "data/out/x/elements.json" in joined
    assert "findings.xlsx" in joined
    assert "ok.py" not in joined and ".gitkeep" not in joined


def test_oversized_files_and_notebook_outputs_are_blocked():
    problems = guard.check_paths({"big.txt": 2_000_000}, {"nb.ipynb"})
    assert any("big.txt" in p for p in problems) and any("nb.ipynb" in p for p in problems)


def test_synthetic_fixtures_are_allowed_even_if_they_are_json_or_pdf():
    assert guard.check_paths({"shared/fixtures/mock_a/elements.json": 5000}) == []
    assert guard.check_paths({"shared/fixtures/huge.json": 5_000_000})  # size still limited


def test_secret_patterns_are_detected():
    assert guard.find_secrets("a.py", 'api_key = "abcdef0123456789abcdef"')
    assert guard.find_secrets("b.txt", "-----BEGIN PRIVATE KEY-----")
    assert guard.find_secrets("c.py", "x = 1  # nothing here") == []


def test_local_analysis_notes_and_hand_labels_are_blocked():
    problems = guard.check_paths({"docs/private/baselines.md": 10, "metrics/gold/labels.csv": 10})
    assert any("docs/private/baselines.md" in p for p in problems)
    assert any("metrics/gold/labels.csv" in p for p in problems)
```

Also create the three empty files `backend/l2c/__init__.py`, `backend/tests/__init__.py`, `backend/tests/tooling/__init__.py`.

- [ ] **Step 3: Create the packaging and requirements files (the test cannot run until `pyproject.toml` exists)**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "l2c"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.pytest.ini_options]
pythonpath = ["backend"]
testpaths = ["backend/tests"]
addopts = "-q"
filterwarnings = ["ignore::DeprecationWarning"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["backend"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.setuptools.packages.find]
where = ["backend"]
include = ["l2c*"]
```

Create `requirements.txt`:

```text
# Never edited after day 1: each lane edits only its own file under requirements/.
-r requirements/extract.txt
-r requirements/compare.txt
-r requirements/dev.txt
```

Create `requirements/base.txt`:

```text
pydantic>=2.7
jsonschema>=4.21
numpy>=1.26
```

Create `requirements/extract.txt`:

```text
-r base.txt
pymupdf>=1.24
scipy>=1.12
rapidocr-onnxruntime>=1.3
```

Create `requirements/compare.txt`:

```text
-r base.txt
scipy>=1.12
scikit-learn>=1.4
reportlab>=4.1
openpyxl>=3.1
```

Create `requirements/dev.txt`:

```text
pytest>=8.0
ruff>=0.5
```

Then run `uv pip install -r requirements.txt && uv pip install -e .` again.

- [ ] **Step 4: Run the test to verify it fails**

```bash
python -m pytest backend/tests/tooling/test_guard.py -v
```

Expected: collection error, `FileNotFoundError` / `No such file` for `scripts/guard.py`.

- [ ] **Step 5: Create the guard, hook and helper scripts**

Create `scripts/guard.py`:

```python
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
```

Create `.githooks/pre-commit`:

```text
#!/bin/sh
# Runs on every commit. Uses `python` or `py` so it works in Git Bash on Windows too.
if command -v python >/dev/null 2>&1; then PY=python; elif command -v python3 >/dev/null 2>&1; then PY=python3; else PY="py"; fi
exec "$PY" scripts/guard.py
```

Create `scripts/install_hooks.py`:

```python
"""Enable the committed git hooks for this clone: `python scripts/install_hooks.py`."""

import subprocess
import sys


def main() -> int:
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
    print("git hooks enabled (core.hooksPath=.githooks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Create `scripts/check.py`:

```python
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
```

Create `scripts/purge.py`:

```python
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
```

Create `scripts/licenses.py`:

```python
"""List every installed dependency with its version and declared license (for THIRD_PARTY.md).

Usage: python scripts/licenses.py
Review every line; resolve anything marked UNKNOWN before submission.
"""

from __future__ import annotations

from importlib import metadata

WATCH = {"pymupdf": "AGPL-3.0 (source must ship with the submission)"}


def license_of(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    text = meta.get("License-Expression") or meta.get("License") or ""
    if not text or len(text) > 80:
        classifiers = [
            c.split("::")[-1].strip()
            for c in meta.get_all("Classifier") or []
            if c.startswith("License ::")
        ]
        text = ", ".join(classifiers) or "UNKNOWN"
    return text.splitlines()[0]


def main() -> int:
    rows = sorted((d.metadata["Name"], d.version, license_of(d)) for d in metadata.distributions())
    width = max(len(n) for n, _, _ in rows)
    for name, version, lic in rows:
        note = f"   <-- {WATCH[name.lower()]}" if name.lower() in WATCH else ""
        print(f"{name:<{width}}  {version:<12} {lic}{note}")
    unknown = [n for n, _, lic in rows if lic == "UNKNOWN"]
    print(f"\n{len(rows)} packages; {len(unknown)} with unknown license: {unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Add repository hygiene files**

Create `.gitattributes`:

```text
* text=auto eol=lf
*.pdf binary
*.xlsx binary
*.png binary
```

Create `.github/CODEOWNERS`, then replace `IAN_GITHUB_USERNAME` with Ian's GitHub login (one edit; ask Ian):

```text
# Each lane edits only its own folders; shared/ changes go through a contract PR reviewed by both.
/backend/l2c/ingest/        @erickossovsky
/backend/l2c/extract/       @erickossovsky
/backend/tests/extract/     @erickossovsky
/backend/l2c/compare/       @IAN_GITHUB_USERNAME
/backend/l2c/match/         @IAN_GITHUB_USERNAME
/backend/l2c/report/        @IAN_GITHUB_USERNAME
/backend/l2c/mock/          @IAN_GITHUB_USERNAME
/backend/tests/compare/     @IAN_GITHUB_USERNAME
/frontend/                  @IAN_GITHUB_USERNAME
/shared/                    @erickossovsky @IAN_GITHUB_USERNAME
/backend/l2c/contract/      @erickossovsky @IAN_GITHUB_USERNAME
```

Append to `.gitignore`:

```text
# ---- L2C: confidential data and generated outputs never reach git (spec 10.21)
data/*
!data/.gitkeep
deliverables/
demo/
metrics/gold/
models/
docs/private/
*.pdf
!shared/fixtures/**/*.pdf
*.dxf
*.dwg
*.ifc
*.bcf
*.bcfzip
*.xlsx
*.xls
*.zip
*.onnx
*.pkl
*.joblib
.venv/
*.egg-info/
.pytest_cache/
.ruff_cache/
```

Replace `README.md`:

```markdown
# L2C: From Plans to Shop Drawings

Checks reinforcement shop drawings against structural plans. PDFs go in; a JSON metadata
database (Appendix A schema), per-shop-drawing comparison files and PDF reports come out.
Everything runs locally and offline; confidential drawings never leave the machine.

## Setup (macOS, Linux, Windows)

```
uv venv --python 3.12 .venv
# macOS/Linux: source .venv/bin/activate      Windows: .venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
uv pip install -e .
python scripts/install_hooks.py      # enables the data/secret guard on every commit
python scripts/check.py              # lint + format + tests + guard
```

## Run

```
python -m l2c.extract <project_dir> --out data/out/<project>/metadata [--ocr] [--config c.json]
python -m l2c.compare data/out/<project>/metadata --out data/out/<project> [--ml]
```

`<project_dir>` holds the plan PDF(s) and a `DA/` folder of shop drawings. Both commands print
counts only, never drawing values.

## Lanes

- `backend/l2c/{ingest,extract}`: PDF to metadata (Eric). Deterministic rules; OCR only for pages
  without a text layer.
- `backend/l2c/{match,compare,report,mock}`: metadata to comparison files and reports (Ian).
- `backend/l2c/contract`, `shared/`: the contract between the lanes (both; contract PRs only).

## Data rules

Real drawings and everything derived from them live under `data/`, `deliverables/` or `demo/`
(git-ignored). `python scripts/purge.py --yes` removes them at the end of the event.
```

Create `THIRD_PARTY.md`:

```markdown
# Third-party software

Run `python scripts/licenses.py` and paste the table here. Resolve every UNKNOWN before submission.

| Package | License | Note |
|---|---|---|
| PyMuPDF | AGPL-3.0 (or commercial) | free and open source; our source ships with the submission |
| pydantic, jsonschema, openpyxl, onnxruntime, pytest, ruff | MIT | |
| numpy, scipy, scikit-learn | BSD-3-Clause | |
| reportlab | BSD (open-source edition) | |
| rapidocr-onnxruntime | Apache-2.0 | models bundled in the wheel; no download at run time |
```

- [ ] **Step 7: Run the tests and the checker**

```bash
python -m pytest backend/tests/tooling -v
python scripts/install_hooks.py
python scripts/check.py
```

Expected: 5 passed; `CHECK PASSED` (the guard step prints nothing when nothing is staged).

- [ ] **Step 8: Prove the hook really blocks confidential files**

```bash
echo test > probe.pdf
git add -f probe.pdf
git commit -m "probe"
```

Expected: `COMMIT BLOCKED by scripts/guard.py` naming `probe.pdf`; no commit is created. Then clean up: `git reset probe.pdf && rm probe.pdf`.

- [ ] **Step 9: Commit and merge to dev**

```bash
git add .gitignore .gitattributes .github .githooks pyproject.toml requirements.txt requirements scripts backend README.md THIRD_PARTY.md
git commit -m "Add scaffold, requirements and data guard"
```

```bash
git switch dev && git merge --no-ff eric/f1-scaffold
```


---

### Task F2: The metadata contract (Eric)

**Files:**
- Create: `backend/l2c/contract/__init__.py` (empty), `constants.py`, `models.py`, `ids.py`, `io.py`
- Create: `scripts/export_schemas.py`, `shared/schemas/*.json` (generated)
- Test: `backend/tests/contract/__init__.py` (empty), `backend/tests/contract/test_contract.py`

**Interfaces:**
- Produces (used by every other task in both lanes): `l2c.contract.constants` (`CONTRACT_VERSION`, `ELEMENT_TYPES`, status/check-type names, tolerances, quality weights, thresholds); `l2c.contract.models` (`Armature`, `ElementStrict`, `ElementExt`, `MatchKey`, `Quality`, `AttrQuality`, `LocationQuality`, `GridSheet`, `LevelInfo`, `SheetInfo`, `IdRow`, `Manifest`, `Finding`, `Evidence`, `Ref`, `Diff`, `ComparisonFile`, ...); `l2c.contract.io` (`MetaBundle`, `write_bundle(dir, bundle)`, `read_bundle(dir) -> MetaBundle`, `write_models`, `read_models`, `dumps`, `ContractVersionError`); `l2c.contract.ids.global_id(key_str) -> str` (22 characters).
- `MatchKey.key_str()` format: `type|level|row|col` (`colonne|N4|I|13`); spans append `|from-to`.

- [ ] **Step 1: Start the branch**

```bash
git switch dev && git switch -c eric/f2-contract
```

- [ ] **Step 2: Write the failing contract test**

Create empty `backend/tests/contract/__init__.py`, then:

Create `backend/tests/contract/test_contract.py`:

```python
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from l2c.contract import constants as C
from l2c.contract.ids import compress_guid, global_id
from l2c.contract.io import ContractVersionError, MetaBundle, dumps, read_bundle, write_bundle
from l2c.contract.models import (
    Armature,
    ElementExt,
    ElementStrict,
    LocationQuality,
    MatchKey,
    Quality,
)


def make_element(**over) -> ElementExt:
    base = dict(
        id="S-500_C-K6_plan",
        source="plan",
        fichier="plan.pdf",
        feuillet="S-500",
        page=1,
        x=412.5,
        y=318.0,
        type_element="colonne",
        element="D-6",
        armature=[Armature(repere="K6-V", diametre="25M", quantite=4)],
        match_key=MatchKey(type="colonne", level="N2", row="K", col=6),
        grid="D-6",
        level="N2",
        bbox=(400.0, 310.0, 430.0, 326.0),
        quality=Quality(
            overall=0.9,
            type_conf=1.0,
            level_conf=1.0,
            location=LocationQuality(page_xy_conf=1.0, anchor="outline", grid_conf=0.9),
        ),
        extraction_method="rules",
    )
    base.update(over)
    return ElementExt(**base)


def test_strict_projection_has_only_appendix_a_fields():
    strict = make_element().to_strict()
    assert set(strict.model_dump()) == {
        "id",
        "source",
        "fichier",
        "feuillet",
        "page",
        "x",
        "y",
        "type_element",
        "element",
        "armature",
    }


def test_strict_model_rejects_extras():
    with pytest.raises(ValidationError):
        ElementStrict(
            id="a",
            source="plan",
            fichier="f",
            feuillet=None,
            page=1,
            x=0,
            y=0,
            type_element="colonne",
            element="e",
            armature=[],
            bogus=1,
        )


def test_match_key_string_is_stable_and_handles_fractions():
    assert MatchKey(type="colonne", level="N4", row="I", col=13).key_str() == "colonne|N4|I|13"
    assert MatchKey(type="colonne", level="N4", row="A", col=15.8).key_str() == "colonne|N4|A|15.8"
    assert (
        MatchKey(type="poutre", level="N2", row="K", span_from=5, span_to=8).key_str()
        == "poutre|N2|K||5-8"
    )


def test_global_id_deterministic_and_22_chars():
    a = global_id("colonne|N4|I|13")
    assert a == global_id("colonne|N4|I|13")
    assert a != global_id("colonne|N4|I|14")
    assert len(a) == 22
    assert len(compress_guid("0" * 32)) == 22


def test_dumps_is_stable():
    assert dumps({"b": 1, "a": [1, 2]}) == dumps({"a": [1, 2], "b": 1})
    assert dumps({"a": 1}).endswith("\n")


def test_bundle_round_trip_and_strict_file(tmp_path: Path):
    bundle = MetaBundle(project="demo", elements=[make_element()])
    write_bundle(tmp_path, bundle)
    again = read_bundle(tmp_path)
    assert again.elements[0] == bundle.elements[0]
    strict = json.loads((tmp_path / C.FILE_ELEMENTS_STRICT).read_text(encoding="utf-8"))
    assert isinstance(strict, list) and "quality" not in strict[0]
    first = (tmp_path / C.FILE_ELEMENTS_EXT).read_bytes()
    write_bundle(tmp_path, bundle)
    assert first == (tmp_path / C.FILE_ELEMENTS_EXT).read_bytes()  # byte-identical rerun


def test_contract_version_mismatch_fails_loudly(tmp_path: Path):
    write_bundle(tmp_path, MetaBundle(project="demo", elements=[make_element()]))
    manifest = tmp_path / C.FILE_MANIFEST
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["contract_version"] = "9.9.9"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ContractVersionError):
        read_bundle(tmp_path)


def test_committed_json_schemas_match_the_models():
    """If this fails, run `python scripts/export_schemas.py` and commit shared/schemas/ together
    with the model change (a contract PR)."""
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "export_schemas", root / "scripts" / "export_schemas.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from pydantic import TypeAdapter

    for name, tp in mod.SCHEMAS.items():
        committed = json.loads((root / "shared" / "schemas" / name).read_text(encoding="utf-8"))
        assert committed == TypeAdapter(tp).json_schema(), name
```

- [ ] **Step 3: Run it to verify it fails**

```bash
python -m pytest backend/tests/contract -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.contract'`.

- [ ] **Step 4: Write the contract code**

Create empty `backend/l2c/contract/__init__.py`, then:

Create `backend/l2c/contract/constants.py`:

```python
"""Shared constants. Single source of truth for both lanes (changes need a contract PR)."""

CONTRACT_VERSION = "0.1.0"

TYPE_FONDATION = "fondation"
TYPE_POUTRE = "poutre"
TYPE_MUR = "mur_refend"
TYPE_COLONNE = "colonne"
TYPE_DALLE = "dalle"
ELEMENT_TYPES = (TYPE_FONDATION, TYPE_POUTRE, TYPE_MUR, TYPE_COLONNE, TYPE_DALLE)

SOURCE_PLAN = "plan"
SOURCE_SHOP = "shop"

STATUS_COMPLIANT = "compliant"
STATUS_NON_COMPLIANT = "non_compliant"
STATUS_MISSING = "missing"
STATUS_ADDED = "added"
STATUS_NEEDS_REVIEW = "needs_review"
STATUSES = (
    STATUS_COMPLIANT,
    STATUS_NON_COMPLIANT,
    STATUS_MISSING,
    STATUS_ADDED,
    STATUS_NEEDS_REVIEW,
)

CHECK_TYPES = (
    "cross.plan_vs_shop",
    "cross.shop_vs_shop",
    "cross.plan_vs_plan",
    "cross.revision",
    "cross.project",
    "self.peer_outlier",
    "self.level_consistency",
    "self.internal_consistency",
    "self.plausibility",
    "self.duplicate",
)

BAR_SIZES = ("10M", "15M", "20M", "25M", "30M", "35M")

INCH_MM = 25.4
FOOT_MM = 304.8

# Comparison tolerances
SPACING_TOL_MM = 1.0
LENGTH_TOL_MM = 5.0

# Quality weights (shared/constants.py is the one place to tune them)
OCR_SNAP_PENALTY = 0.9
DERIVED_PENALTY = 0.8
LOOSE_PATTERN_FACTOR = 0.8
CONSISTENCY_FAIL_FACTOR = 0.85
CONSISTENCY_FLOOR = 0.3
ANCHOR_FACTOR = {"outline": 1.0, "label": 0.95, "mark_axis": 0.8, "text_only": 0.5}

# Internal consistency: tie count x spacing / storey height. The accepted band is learned from the
# project's own shop elements (median +/- K robust sigmas); the fixed band is only a fallback
# when there are too few samples.
TIE_RATIO_MIN = 0.8
TIE_RATIO_MAX = 1.3
TIE_BAND_K = 6.0
TIE_BAND_SIGMA_FLOOR = 0.05  # of the median, so a very uniform project does not get a zero band
TIE_BAND_MIN_SAMPLES = 20

# Peer outlier detection
PEER_MIN_GROUP = 8
PEER_MODE_SHARE_MIN = 0.6
PEER_RARE_SHARE_MAX = 0.1

# Finding status thresholds
TRUST_MIN_FOR_VERDICT = 0.7
ANOMALY_ESCALATE = 0.8
PAIR_PROB_ESCALATE = 0.6

# Canonical level names
LEVEL_SS = "SS"
LEVEL_RDC = "RDC"
LEVEL_TOIT = "TOIT"

# Output file names inside a metadata directory
FILE_MANIFEST = "manifest.json"
FILE_ELEMENTS_STRICT = "elements.json"
FILE_ELEMENTS_EXT = "elements.ext.json"
FILE_GRID = "grid.json"
FILE_LEVELS = "levels.json"
FILE_SHEETS = "sheets.json"
FILE_IDS = "ids.json"
```

Create `backend/l2c/contract/models.py`:

```python
"""Pydantic models that define the metadata contract between the extract and compare lanes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from l2c.contract.constants import ELEMENT_TYPES  # noqa: F401  (documented source of the literals)

ElementType = Literal["fondation", "poutre", "mur_refend", "colonne", "dalle"]
Source = Literal["plan", "shop"]
Status = Literal["compliant", "non_compliant", "missing", "added", "needs_review"]
CheckType = Literal[
    "cross.plan_vs_shop",
    "cross.shop_vs_shop",
    "cross.plan_vs_plan",
    "cross.revision",
    "cross.project",
    "self.peer_outlier",
    "self.level_consistency",
    "self.internal_consistency",
    "self.plausibility",
    "self.duplicate",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- Appendix A
class Armature(_Strict):
    repere: str | None = None
    diametre: str | None = None
    quantite: int | None = None
    espacement_mm: float | None = None
    longueur_mm: float | None = None


class ElementStrict(_Strict):
    """Exactly the Appendix A record. Nothing else may be added."""

    id: str
    source: Source
    fichier: str
    feuillet: str | None
    page: int
    x: float
    y: float
    type_element: ElementType
    element: str
    armature: list[Armature]


# --------------------------------------------------------------------------- extensions
class MatchKey(_Strict):
    type: ElementType
    level: str
    row: str | None = None  # grid letter
    col: float | None = None  # grid number, fractional allowed (10.8)
    span_from: float | None = None
    span_to: float | None = None

    def key_str(self) -> str:
        col = "" if self.col is None else f"{self.col:g}"
        if self.span_from is not None or self.span_to is not None:
            sf = "" if self.span_from is None else f"{self.span_from:g}"
            st = "" if self.span_to is None else f"{self.span_to:g}"
            return f"{self.type}|{self.level}|{self.row or ''}|{col}|{sf}-{st}"
        return f"{self.type}|{self.level}|{self.row or ''}|{col}"


class AttrQuality(_Strict):
    value: float | int | str | None = None
    conf: float = Field(ge=0.0, le=1.0)
    status: Literal["parsed", "derived", "inferred", "missing"] = "parsed"
    text_source: Literal["native", "ocr", "vlm"] = "native"
    ocr_conf: float | None = None
    snapped: bool = False
    original_text: str | None = None


class LocationQuality(_Strict):
    page_xy_conf: float = Field(ge=0.0, le=1.0)
    anchor: Literal["outline", "label", "mark_axis", "text_only"]
    anchor_dist_pt: float | None = None
    grid_cell: str | None = None
    grid_conf: float = Field(ge=0.0, le=1.0)
    binding_method: str = "none"
    assignment_cost: float | None = None
    margin_to_runner_up: float | None = None


class Quality(_Strict):
    overall: float = Field(ge=0.0, le=1.0)
    type_conf: float = Field(ge=0.0, le=1.0)
    level_conf: float = Field(ge=0.0, le=1.0)
    location: LocationQuality
    attributes: dict[str, AttrQuality] = Field(default_factory=dict)
    consistency_passed: list[str] = Field(default_factory=list)
    consistency_failed: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class ElementExt(ElementStrict):
    match_key: MatchKey
    grid: str | None = None
    level: str
    section_mm: tuple[float, float] | None = None
    bbox: tuple[float, float, float, float]
    quality: Quality
    extraction_method: str
    raw_text: str | None = None
    provenance: dict[str, str | int | float] = Field(default_factory=dict)

    def to_strict(self) -> ElementStrict:
        data = self.model_dump(include=set(ElementStrict.model_fields))
        return ElementStrict.model_validate(data)


# --------------------------------------------------------------------------- side files
class GridSheet(_Strict):
    fichier: str
    page: int
    feuillet: str | None
    # Letters name the rows and numbers the columns of the match key. Their page positions are
    # y (letters_on="y", letters run down an edge) or x (letters_on="x", letters run along an edge).
    letters_on: Literal["x", "y"] = "y"
    rows: dict[str, float]  # letter -> position along its axis, PDF points (top-left origin)
    cols: dict[str, float]  # number label -> position along its axis, PDF points


class LevelInfo(_Strict):
    level: str  # canonical: SS, RDC, N2, N3, ..., TOIT
    name: str
    elevation_mm: float | None = None


class SheetInfo(_Strict):
    fichier: str
    page: int
    feuillet: str | None
    kind: Source
    type_element: ElementType | None
    level: str | None
    layer: Literal["text", "vector", "image", "empty"]
    width: float
    height: float
    rotation: int
    revision: str | None = None
    layout: str | None = None  # which adapter ran, or why none did (coverage reporting)


class IdRow(_Strict):
    element_id: str
    match_key: str
    global_id: str


class Manifest(_Strict):
    contract_version: str
    project: str
    counts: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- findings
class Ref(_Strict):
    element_id: str | None
    fichier: str
    page: int
    x: float
    y: float


class Diff(_Strict):
    field: str
    plan: float | int | str | None
    shop: float | int | str | None
    delta: float | None = None


class RuleEvidence(_Strict):
    fired: bool
    kind: str
    diffs: list[Diff] = Field(default_factory=list)


class ExtractionEvidence(_Strict):
    plan_overall: float | None = None
    shop_overall: float | None = None
    flags: list[str] = Field(default_factory=list)


class MatchEvidence(_Strict):
    method: str
    assignment_cost: float | None = None
    margin_to_runner_up: float | None = None


class MlEvidence(_Strict):
    peer_anomaly: float | None = None
    pair_probability: float | None = None
    model_version: str | None = None


class Evidence(_Strict):
    rule: RuleEvidence
    extraction: ExtractionEvidence
    match: MatchEvidence | None = None
    ml: MlEvidence | None = None
    llm_rationale: str | None = None


class Finding(_Strict):
    id: str
    check_type: CheckType
    status: Status
    type_element: ElementType
    level: str
    grid: str | None
    plan_ref: Ref | None = None
    shop_ref: Ref | None = None
    diffs: list[Diff] = Field(default_factory=list)
    evidence: Evidence
    trust: float = Field(ge=0.0, le=1.0)
    discrepancy_probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str = ""


class ComparisonFile(_Strict):
    contract_version: str
    shop_file: str
    revision: str | None = None
    plan_sheets: list[str] = Field(default_factory=list)
    counts: dict[str, int]
    findings: list[Finding]
```

Create `backend/l2c/contract/ids.py`:

```python
"""Deterministic identities: match key string -> UUID5 -> IFC-compressed GlobalId."""

import uuid

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
_NAMESPACE = uuid.UUID("6f1d2c3e-0000-4000-8000-00000000a2c1")


def _b64(value: int, length: int) -> str:
    return "".join(_CHARS[(value // (64**i)) % 64] for i in range(length))[::-1]


def compress_guid(hex32: str) -> str:
    """Compress a 32-char hex GUID to the 22-char IFC GlobalId form."""
    b = [int(hex32[i : i + 2], 16) for i in range(0, 32, 2)]
    parts = [_b64(b[0], 2)]
    for i in range(1, 16, 3):
        parts.append(_b64((b[i] << 16) + (b[i + 1] << 8) + b[i + 2], 4))
    return "".join(parts)


def global_id(key_str: str) -> str:
    """Same key string always yields the same 22-character id."""
    return compress_guid(uuid.uuid5(_NAMESPACE, key_str).hex)
```

Create `backend/l2c/contract/io.py`:

```python
"""Deterministic JSON read/write and the metadata bundle (one folder per project)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from l2c.contract import constants as C
from l2c.contract.models import (
    ElementExt,
    ElementStrict,
    GridSheet,
    IdRow,
    LevelInfo,
    Manifest,
    SheetInfo,
)


class ContractVersionError(RuntimeError):
    """Raised when a file was written with a different contract version."""


def dumps(obj: object) -> str:
    """Stable text: sorted keys, 2-space indent, trailing newline, UTF-8 friendly."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_models(path: Path, models: list[BaseModel] | BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        [m.model_dump(mode="json") for m in models]
        if isinstance(models, list)
        else models.model_dump(mode="json")
    )
    path.write_text(dumps(data), encoding="utf-8", newline="\n")


def read_models[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return TypeAdapter(list[model]).validate_python(raw)


@dataclass
class MetaBundle:
    """Everything Eric's lane writes and Ian's lane reads."""

    project: str
    elements: list[ElementExt] = field(default_factory=list)
    grids: list[GridSheet] = field(default_factory=list)
    levels: list[LevelInfo] = field(default_factory=list)
    sheets: list[SheetInfo] = field(default_factory=list)
    ids: list[IdRow] = field(default_factory=list)


def write_bundle(directory: Path, bundle: MetaBundle) -> None:
    from l2c.contract.ids import global_id

    ordered = sorted(bundle.elements, key=lambda e: (e.source, e.fichier, e.page, e.id))
    ids = [
        IdRow(
            element_id=e.id,
            match_key=e.match_key.key_str(),
            global_id=global_id(e.match_key.key_str()),
        )
        for e in ordered
    ]
    write_models(directory / C.FILE_ELEMENTS_EXT, ordered)
    write_models(directory / C.FILE_ELEMENTS_STRICT, [e.to_strict() for e in ordered])
    write_models(directory / C.FILE_GRID, sorted(bundle.grids, key=lambda g: (g.fichier, g.page)))
    write_models(directory / C.FILE_LEVELS, bundle.levels)
    write_models(
        directory / C.FILE_SHEETS, sorted(bundle.sheets, key=lambda s: (s.fichier, s.page))
    )
    write_models(directory / C.FILE_IDS, ids)
    manifest = Manifest(
        contract_version=C.CONTRACT_VERSION,
        project=bundle.project,
        counts={
            "elements": len(ordered),
            "plan": sum(1 for e in ordered if e.source == C.SOURCE_PLAN),
            "shop": sum(1 for e in ordered if e.source == C.SOURCE_SHOP),
        },
    )
    write_models(directory / C.FILE_MANIFEST, manifest)


def read_bundle(directory: Path) -> MetaBundle:
    manifest_path = directory / C.FILE_MANIFEST
    manifest = Manifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.contract_version != C.CONTRACT_VERSION:
        raise ContractVersionError(
            f"{manifest_path} has contract_version {manifest.contract_version}, "
            f"this code expects {C.CONTRACT_VERSION}"
        )
    return MetaBundle(
        project=manifest.project,
        elements=read_models(directory / C.FILE_ELEMENTS_EXT, ElementExt),
        grids=read_models(directory / C.FILE_GRID, GridSheet),
        levels=read_models(directory / C.FILE_LEVELS, LevelInfo),
        sheets=read_models(directory / C.FILE_SHEETS, SheetInfo),
        ids=read_models(directory / C.FILE_IDS, IdRow),
    )


def strict_records(directory: Path) -> list[ElementStrict]:
    return read_models(directory / C.FILE_ELEMENTS_STRICT, ElementStrict)
```

- [ ] **Step 5: Write the schema exporter and generate the schemas**

Create `scripts/export_schemas.py`:

```python
"""Regenerate shared/schemas/*.json from the pydantic models (run after any contract change)."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from l2c.contract.models import (
    ComparisonFile,
    ElementExt,
    ElementStrict,
    Finding,
    GridSheet,
    IdRow,
    LevelInfo,
    Manifest,
    SheetInfo,
)

OUT = Path(__file__).resolve().parents[1] / "shared" / "schemas"

SCHEMAS = {
    "elements.schema.json": list[ElementStrict],
    "elements.ext.schema.json": list[ElementExt],
    "grid.schema.json": list[GridSheet],
    "levels.schema.json": list[LevelInfo],
    "sheets.schema.json": list[SheetInfo],
    "ids.schema.json": list[IdRow],
    "findings.schema.json": list[Finding],
    "comparison.schema.json": ComparisonFile,
    "manifest.schema.json": Manifest,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, tp in SCHEMAS.items():
        schema = TypeAdapter(tp).json_schema()
        (OUT / name).write_text(
            json.dumps(schema, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    print(f"wrote {len(SCHEMAS)} schemas to {OUT}")


if __name__ == "__main__":
    main()
```

```bash
python scripts/export_schemas.py
```

Expected: `wrote 9 schemas to .../shared/schemas`.

- [ ] **Step 6: Run the tests and lint**

```bash
python -m pytest backend/tests/contract -v
python scripts/check.py
```

Expected: all pass, including `test_committed_json_schemas_match_the_models`.

- [ ] **Step 7: Commit as a contract PR (announce it in chat; Ian reviews and merges within 15 minutes)**

```bash
git add backend/l2c/contract backend/tests/contract scripts/export_schemas.py shared/schemas
git commit -m "Add metadata contract and schemas"
```

```bash
git switch dev && git merge --no-ff eric/f2-contract
```


---

### Task F3: Hand-off checkpoint (Eric then Ian)

**Files:** none.

- [ ] **Step 1: Share dev**

Eric pushes `dev` (or sends the git bundle, see the note at the top). Ian runs `git fetch && git switch dev && git pull`, activates his environment (Task I0 of his plan) and runs `python scripts/check.py`. Expected on both machines: `CHECK PASSED`.

- [ ] **Step 2: Agree on the contract in a 10-minute call**

Walk through `ElementExt`, `Quality`, `Finding` and `Evidence`. Any wording change is made now, in a contract PR; after this point the contract changes only with both people's agreement and regenerated schemas/fixtures in the same commit. Note the agreed `contract_version` (`0.1.0`).


---

### Task F4: Mock project and committed fixtures (Ian)

**Files:**
- Create: `backend/l2c/mock/__init__.py` (empty), `backend/l2c/mock/elements.py`, `backend/l2c/mock/generate.py`
- Create: `scripts/make_fixtures.py`, `shared/fixtures/mock_a/**` (generated)
- Test: `backend/tests/compare/__init__.py` (empty), `backend/tests/compare/test_mock.py`, `backend/tests/contract/test_fixtures.py`

**Interfaces:**
- Produces: `l2c.mock.elements.make_element(source, level, row, col, *, count=4, size="25M", tie_size="10M", spacing_mm=152.4, tie_count=None, fichier=None, page=1, overall=0.95, flags=(), feuillet=None, x=100.0, y=100.0, type_element="colonne", armature=None) -> ElementExt` (synthetic element with consistent quality); `l2c.mock.generate.mock_project() -> MockProject` with `.bundle: MetaBundle` and `.expected: list[Expected(check_type, status, level, grid, note)]` describing exactly which non-compliant findings the comparison must produce; the committed folder `shared/fixtures/mock_a/` (`metadata/` plus `expected_findings.json`).
- The mock project injects: a count mismatch, a spacing mismatch, a missing element, an added element, a size outlier among peers (plan odd, shop typical: the shape of the real known cases), a difference seen through a weak extraction (must not be a firm verdict), an internal inconsistency (impossible tie count), a conflicting duplicate across two shop files, a harmless duplicate, an unbound plan block, and a shop block on a level with no plan sheet.

- [ ] **Step 1: Start the branch and write the failing tests**

```bash
git switch dev && git pull && git switch -c ian/f4-mock
```

Create empty `backend/tests/compare/__init__.py`, then:

Create `backend/tests/compare/test_mock.py`:

```python
from collections import Counter

from l2c.mock.generate import mock_project


def test_mock_project_shape_is_stable():
    m = mock_project()
    plan = [e for e in m.bundle.elements if e.source == "plan"]
    shop = [e for e in m.bundle.elements if e.source == "shop"]
    assert len(plan) == 24 + 1  # 2 levels x 2 rows x 6 cols, plus one unbound block
    assert len(shop) == 24 - 1 + 1 + 1 + 1 + 1  # one missing, plus added, two duplicates, FDN
    assert len({e.id for e in m.bundle.elements}) == len(m.bundle.elements)
    assert Counter(x.check_type for x in m.expected)["cross.plan_vs_shop"] == 8


def test_mock_defects_are_visible_in_the_data():
    m = mock_project()
    by = {(e.source, e.level, e.grid): e for e in m.bundle.elements if e.grid}
    assert by[("shop", "N2", "K-4")].armature[0].quantite == 6
    assert by[("plan", "N2", "K-5")].armature[0].diametre == "35M"
    assert ("shop", "N2", "L-8") not in by
    assert by[("shop", "N3", "L-5")].armature[1].espacement_mm == 304.8
```

Create `backend/tests/contract/test_fixtures.py`:

```python
"""Fixtures are the shared definition of the metadata. Both lanes run these tests."""

import json
from pathlib import Path

from l2c.contract.io import read_bundle, write_bundle


def test_committed_fixtures_match_the_mock_generator():
    """If this fails after editing backend/l2c/mock/, run `python scripts/make_fixtures.py`."""
    import tempfile

    from l2c.mock.generate import mock_project

    root = Path(__file__).resolve().parents[3] / "shared" / "fixtures" / "mock_a" / "metadata"
    with tempfile.TemporaryDirectory() as tmp:
        write_bundle(Path(tmp), mock_project().bundle)
        for f in sorted(p.name for p in Path(tmp).iterdir()):
            assert (Path(tmp) / f).read_bytes() == (root / f).read_bytes(), f


def test_fixture_bundle_loads_and_validates_against_the_schemas():
    import jsonschema

    root = Path(__file__).resolve().parents[3] / "shared"
    meta = root / "fixtures" / "mock_a" / "metadata"
    bundle = read_bundle(meta)
    assert len(bundle.elements) > 40
    for data_file, schema_file in [
        ("elements.json", "elements.schema.json"),
        ("elements.ext.json", "elements.ext.schema.json"),
        ("sheets.json", "sheets.schema.json"),
    ]:
        data = json.loads((meta / data_file).read_text(encoding="utf-8"))
        schema = json.loads((root / "schemas" / schema_file).read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest backend/tests/compare/test_mock.py backend/tests/contract/test_fixtures.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.mock'`.

- [ ] **Step 3: Write the mock builders**

Create empty `backend/l2c/mock/__init__.py`, then:

Create `backend/l2c/mock/elements.py`:

```python
"""Synthetic ElementExt builders. Mock data is clearly synthetic: no real drawing values."""

from __future__ import annotations

from l2c.contract.models import (
    Armature,
    AttrQuality,
    ElementExt,
    LocationQuality,
    MatchKey,
    Quality,
)

TIE_COUNT_FOR_3500 = 23  # round(3500 / 152.4)


def make_element(
    source: str,
    level: str,
    row: str | None,
    col: float | None,
    *,
    count: int | None = 4,
    size: str | None = "25M",
    tie_size: str | None = "10M",
    spacing_mm: float | None = 152.4,
    tie_count: int | None = None,
    fichier: str | None = None,
    page: int = 1,
    overall: float = 0.95,
    flags: tuple[str, ...] = (),
    feuillet: str | None = None,
    x: float = 100.0,
    y: float = 100.0,
    type_element: str = "colonne",
    armature: list[Armature] | None = None,
) -> ElementExt:
    grid = f"{row}-{col:g}" if row is not None and col is not None else None
    sheet = feuillet or ("S-500" if source == "plan" else "PART1")
    file = fichier or ("plan.pdf" if source == "plan" else "DA/Colonnes/PART1.pdf")
    if source == "plan":
        element_id = f"{sheet}_{grid or 'U'}_plan" if grid else f"{sheet}_U{int(x)}_plan"
    else:
        stem = file.rsplit("/", 1)[-1].removesuffix(".pdf")
        element_id = f"{stem}_p{page}_{grid or 'U'}_{level}_shop"
    attrs = {
        "count": AttrQuality(value=count, conf=overall),
        "size": AttrQuality(value=size, conf=overall),
    }
    quality = Quality(
        overall=overall,
        type_conf=1.0,
        level_conf=1.0,
        location=LocationQuality(
            page_xy_conf=1.0,
            anchor="outline" if source == "plan" else "label",
            grid_cell=grid,
            grid_conf=1.0 if grid else 0.1,
        ),
        attributes=attrs,
        flags=list(flags),
    )
    return ElementExt(
        id=element_id,
        source=source,  # type: ignore[arg-type]
        fichier=file,
        feuillet=sheet,
        page=page,
        x=x,
        y=y,
        type_element=type_element,  # type: ignore[arg-type]
        element=grid or element_id,
        armature=armature
        if armature is not None
        else [
            Armature(repere="V", diametre=size, quantite=count),
            Armature(repere="T", diametre=tie_size, quantite=tie_count, espacement_mm=spacing_mm),
        ],
        match_key=MatchKey(type=type_element, level=level, row=row, col=col),  # type: ignore[arg-type]
        grid=grid,
        level=level,
        bbox=(x - 10, y - 5, x + 10, y + 5),
        quality=quality,
        extraction_method="mock",
        provenance={"synthetic": 1},
    )
```

Create `backend/l2c/mock/generate.py`:

```python
"""A small synthetic project with known defects and the findings they must produce.

This is the shared definition of "what the metadata looks like" for both lanes. The same
builder feeds contract tests, golden-file tests and the committed fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

from l2c.contract.io import MetaBundle
from l2c.contract.models import ElementExt, GridSheet, LevelInfo, SheetInfo
from l2c.mock.elements import TIE_COUNT_FOR_3500, make_element

ROWS = ("K", "L")
COLS = (3, 4, 5, 6, 7, 8)
LEVELS = {"N2": 0.0, "N3": 3500.0, "N4": 7000.0}
FILE_A = "DA/Colonnes/PART1.pdf"
FILE_B = "DA/Colonnes/PART2.pdf"


@dataclass(frozen=True)
class Expected:
    check_type: str
    status: str
    level: str
    grid: str | None
    note: str = ""


@dataclass
class MockProject:
    bundle: MetaBundle
    expected: list[Expected]


def _typical(source: str, level: str, row: str, col: int, **kw) -> ElementExt:
    fichier = "plan.pdf" if source == "plan" else (FILE_A if row == "K" else FILE_B)
    feuillet = {"N2": "S-517", "N3": "S-518"}[level] if source == "plan" else None
    return make_element(
        source,
        level,
        row,
        col,
        fichier=fichier,
        feuillet=feuillet,
        tie_count=TIE_COUNT_FOR_3500 if source == "shop" else None,
        x=100.0 + 40 * col,
        y=100.0 + (60 if row == "K" else 120),
        **kw,
    )


def mock_project() -> MockProject:
    plan: list[ElementExt] = []
    shop: list[ElementExt] = []
    for level in ("N2", "N3"):
        for row in ROWS:
            for col in COLS:
                plan.append(_typical("plan", level, row, col))
                shop.append(_typical("shop", level, row, col))

    def replace(lst: list[ElementExt], level: str, row: str, col: int, new: ElementExt) -> None:
        for i, e in enumerate(lst):
            if (e.level, e.match_key.row, e.match_key.col) == (level, row, col):
                lst[i] = new
                return
        raise KeyError((level, row, col))

    def drop(lst: list[ElementExt], level: str, row: str, col: int) -> None:
        lst[:] = [
            e for e in lst if (e.level, e.match_key.row, e.match_key.col) != (level, row, col)
        ]

    expected: list[Expected] = []
    # 1. count mismatch (plan 4 vs shop 6)
    replace(shop, "N2", "K", 4, _typical("shop", "N2", "K", 4, count=6))
    expected.append(Expected("cross.plan_vs_shop", "non_compliant", "N2", "K-4", "count"))
    # 2. spacing mismatch (plan 6" vs shop 12")
    replace(
        shop,
        "N3",
        "L",
        5,
        make_element(
            "shop", "N3", "L", 5, fichier=FILE_B, spacing_mm=304.8, tie_count=11, x=300.0, y=220.0
        ),
    )
    expected.append(Expected("cross.plan_vs_shop", "non_compliant", "N3", "L-5", "spacing"))
    # 3. missing from shop drawings
    drop(shop, "N2", "L", 8)
    expected.append(Expected("cross.plan_vs_shop", "missing", "N2", "L-8"))
    # 4. added in shop drawings (column 9 does not exist on the plan)
    shop.append(_typical("shop", "N3", "K", 9))
    expected.append(Expected("cross.plan_vs_shop", "added", "N3", "K-9"))
    # 5. the realistic known case: plan has one odd size among peers, shop has the typical value
    replace(plan, "N2", "K", 5, _typical("plan", "N2", "K", 5, size="35M"))
    expected.append(Expected("cross.plan_vs_shop", "non_compliant", "N2", "K-5", "size"))
    expected.append(Expected("self.peer_outlier", "needs_review", "N2", "K-5", "size"))
    # 6. a difference seen through an unreliable extraction: must NOT be a firm verdict
    replace(
        shop,
        "N3",
        "K",
        4,
        make_element(
            "shop",
            "N3",
            "K",
            4,
            fichier=FILE_A,
            count=5,
            tie_count=TIE_COUNT_FOR_3500,
            overall=0.4,
            flags=("weak_strip_assignment",),
            x=260.0,
            y=160.0,
        ),
    )
    expected.append(Expected("cross.plan_vs_shop", "needs_review", "N3", "K-4", "low trust"))
    # 7. internal inconsistency: 34 ties at 6" cannot fit a 3500 mm storey
    replace(
        shop,
        "N2",
        "L",
        3,
        make_element("shop", "N2", "L", 3, fichier=FILE_B, tie_count=34, x=220.0, y=220.0),
    )
    expected.append(Expected("self.internal_consistency", "needs_review", "N2", "L-3"))
    # 8. conflicting duplicate across two shop files
    shop.append(
        make_element(
            "shop",
            "N3",
            "K",
            7,
            fichier=FILE_B,
            count=8,
            tie_count=TIE_COUNT_FOR_3500,
            page=2,
            x=380.0,
            y=160.0,
        )
    )
    expected.append(Expected("cross.shop_vs_shop", "needs_review", "N3", "K-7"))
    # 9. benign duplicate (same values in both files): no finding expected
    shop.append(
        make_element(
            "shop",
            "N3",
            "K",
            8,
            fichier=FILE_B,
            tie_count=TIE_COUNT_FOR_3500,
            page=2,
            x=420.0,
            y=160.0,
        )
    )
    # 10. plan block that could not be bound to a grid cell
    plan.append(
        make_element(
            "plan",
            "N3",
            None,
            None,
            feuillet="S-518",
            flags=("unbound_block",),
            overall=0.1,
            x=900.0,
            y=900.0,
        )
    )
    expected.append(Expected("cross.plan_vs_shop", "needs_review", "N3", None, "unbound"))
    # 11. shop block below the lowest level line (foundation dowels): level has no plan sheet
    shop.append(
        make_element(
            "shop", "FDN", "K", 3, fichier=FILE_A, tie_count=None, spacing_mm=None, x=140.0, y=700.0
        )
    )
    expected.append(Expected("cross.plan_vs_shop", "needs_review", "FDN", "K-3", "level"))

    bundle = MetaBundle(
        project="MOCK",
        elements=plan + shop,
        grids=[
            GridSheet(
                fichier="plan.pdf",
                page=1,
                feuillet="S-517",
                rows={"K": 300.0, "L": 400.0},
                cols={str(c): 100.0 + 40 * c for c in COLS},
            )
        ],
        levels=[LevelInfo(level=k, name=k, elevation_mm=v) for k, v in LEVELS.items()],
        sheets=[
            SheetInfo(
                fichier="plan.pdf",
                page=1,
                feuillet="S-517",
                kind="plan",
                type_element="colonne",
                level="N2",
                layer="text",
                width=3000,
                height=2000,
                rotation=0,
            ),
            SheetInfo(
                fichier="plan.pdf",
                page=2,
                feuillet="S-518",
                kind="plan",
                type_element="colonne",
                level="N3",
                layer="text",
                width=3000,
                height=2000,
                rotation=0,
            ),
            SheetInfo(
                fichier=FILE_A,
                page=1,
                feuillet=None,
                kind="shop",
                type_element="colonne",
                level=None,
                layer="text",
                width=2500,
                height=1700,
                rotation=0,
            ),
            SheetInfo(
                fichier=FILE_B,
                page=1,
                feuillet=None,
                kind="shop",
                type_element="colonne",
                level=None,
                layer="text",
                width=2500,
                height=1700,
                rotation=0,
            ),
        ],
    )
    return MockProject(bundle=bundle, expected=expected)
```

Create `scripts/make_fixtures.py`:

```python
"""Write the synthetic mock project and its expected findings to shared/fixtures/mock_a/.

Run after changing backend/l2c/mock/ (a contract change: both lanes must agree).
Everything written here is synthetic; no real drawing data is involved.
"""

from __future__ import annotations

import json
from pathlib import Path

from l2c.contract.io import dumps, write_bundle
from l2c.mock.generate import mock_project

OUT = Path(__file__).resolve().parents[1] / "shared" / "fixtures" / "mock_a"


def main() -> None:
    m = mock_project()
    write_bundle(OUT / "metadata", m.bundle)
    expected = [
        {
            "check_type": x.check_type,
            "status": x.status,
            "level": x.level,
            "grid": x.grid,
            "note": x.note,
        }
        for x in m.expected
    ]
    (OUT / "expected_findings.json").write_text(dumps(expected), encoding="utf-8", newline="\n")
    (OUT / "README.md").write_text(
        "Synthetic mock project (no real data).\n"
        "Regenerate with `python scripts/make_fixtures.py`.\n"
        "`metadata/` is what Eric's lane writes; `expected_findings.json` is what Ian's lane "
        "must produce from it (every non-compliant row; compliant rows are not listed).\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote fixtures to {OUT} ({len(json.loads(dumps(expected)))} expected findings)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate and commit the fixtures**

```bash
python scripts/make_fixtures.py
```

Expected: `wrote fixtures to .../shared/fixtures/mock_a (11 expected findings)`. The folder now holds `metadata/` (seven JSON files), `expected_findings.json` and a README. They are synthetic, so the guard allows `shared/fixtures/`.

- [ ] **Step 5: Run the tests**

```bash
python -m pytest backend/tests/compare/test_mock.py backend/tests/contract -v
python scripts/check.py
```

Expected: all pass (the fixture-drift test proves the committed files equal what the generator writes).

- [ ] **Step 6: Commit and merge**

```bash
git add backend/l2c/mock backend/tests/compare backend/tests/contract/test_fixtures.py scripts/make_fixtures.py shared/fixtures
git commit -m "Add mock project and fixtures"
```

```bash
git switch dev && git merge --no-ff ian/f4-mock
```

Eric pulls `dev`. From here Ian builds the comparison against `shared/fixtures/mock_a/metadata/` and Eric's extractor must produce files that validate against `shared/schemas/`.

