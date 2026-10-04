# L2C Comparison Lane (Metadata to Comparison) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the metadata bundle, produce every comparison finding (plan against shop, shop against shop, an element against its peers, internal consistency) with a trust-aware status and confidence, and write the per-shop-drawing JSON and PDF, the per-plan-sheet PDF report, the jury-style XLSX and `findings.json`.

**Architecture:** A pure function `run_comparison(bundle)` over contract models. Matching is by `(type, level, grid row, grid column)` with a fractional-column fallback; the comparator is deterministic and defines recall (colonnes by role, other element types by bar group, so it is not tied to one element type); `trust` combines Eric's extraction quality with the match quality; ML can only raise a no-difference pair to `needs_review`. Outputs are views of `findings.json` and the metadata, never of the PDFs. Everything is developed against the committed synthetic fixtures and random fuzz projects, so this lane never waits for the extractor.

**Tech Stack:** Python 3.12, pydantic v2, SciPy (assignment), scikit-learn (second tier), ReportLab (PDF), openpyxl (XLSX).

**Spec:** `docs/superpowers/specs/2026-10-03-l2c-design.md` (sections 4.3 to 4.5, 10.9, 10.17, 10.19, 10.22).

**Prerequisite:** Plan 00 (`docs/superpowers/plans/2026-10-03-l2c-00-shared-foundation.md`) is merged on `dev` through Task F4 (contract, schemas, mock project, committed fixtures). Eric's extraction lane is **not** needed until Task I10.

**Windows note:** every command is a `python -m ...` or `python scripts/...` call that behaves the same in PowerShell; no heredocs or bash-only syntax. Use `\` or `/` in paths as you like; file names inside JSON are always posix paths.

**Tiers and timing (starting about 9 PM):** I0 plus F4 about 60 min; I1 to I5 about 90 min; I6 to I7 about 45 min; I8 about 60 min; that is the core: about 4 hours, ready before Eric's real bundle exists. I10 is the integration gate (about 2 to 3 AM). I9 is second tier.

## Global Constraints

- Python core, **Python 3.12** managed with `uv`; all code uses `pathlib` and writes text with `newline="\n"` (works on macOS and Windows).
- Output JSON must conform to the provided Appendix A schema: strict `elements.json` records contain exactly `id, source, fichier, feuillet, page, x, y, type_element, element, armature` and nothing else; extras live in `elements.ext.json`.
- Coordinates are PDF points of the page **as displayed** (rotation applied once), origin top-left, y downward; `x, y` is the centre of the annotation.
- Spacings written with a quote mark or bare number are inches (`config.default_spacing_unit`); `mm` is always explicit; stored as `espacement_mm`. Bar sizes come from `config.bar_sizes` (default `10M 15M 20M 25M 30M 35M`).
- `contract_version` is `"0.1.0"`; every metadata folder has a `manifest.json`; loaders fail loudly on a mismatch.
- Same input must give byte-identical output (sorted keys, no randomness without a fixed seed).
- **Nothing is hard-coded to one project**: distances are multiples of the page's own word height or gridline spacing (`calibrate.py`); language, notation, units and ratios live in `Config` and can be overridden with `--config file.json`.
- No document may be sent to any cloud service or external AI API; the pipeline imports no network library and runs offline. Confidential data (PDFs, derived JSON/XLSX/PDF outputs, models) is never committed: `data/`, `deliverables/`, `demo/` are git-ignored and `scripts/guard.py` blocks them in the pre-commit hook. Tests use synthetic data only.
- No commercially licensed software; dependencies are open source (PyMuPDF is AGPL-3.0: the source ships with the submission). `THIRD_PARTY.md` lists every dependency and license.
- Each lane edits only its own folders (`.github/CODEOWNERS`); `shared/` and `backend/l2c/contract/` change only through a contract PR reviewed by both people, which also regenerates `shared/schemas/` and `shared/fixtures/` in the same commit.
- Commits: short imperative subject; **no `Co-Authored-By` trailer and no "Generated with" line**. Do not push until Eric lifts the current no-push rule and `git log --all --stat` shows no PDF/XLSX/DXF/IFC/BCF/zip files.

## Review Focus

- A project that does not look like the development ones: different levels, grid size, number of shop files, bar sizes and spacings. Pinned by `test_fuzz.py` (Task I7): 60 random projects, every injected defect found, nothing else flagged.
- Overlapping shop files with identical values (CLP Parts 2 and 3) or conflicting values: identical ones are harmless, conflicting ones become `cross.shop_vs_shop`; the matcher keeps the best quality element as primary. Pinned by `test_duplicates.py` (I5) and `test_matcher.py` (I1).
- Real extractions have low trust almost everywhere: a difference seen at low trust is `needs_review`, never a firm verdict, and a pair with no difference keeps a meaningful confidence (never 0.0). Pinned by `test_fusion.py` (I2), `test_cross.py` (I3), `test_golden.py` (I6); measured on real CLP in Task I10.
- Nothing found or nothing covered (empty project, element types without data): every output is still written and every report states what is `NOT COVERED`. Pinned by `test_outputs.py` (I8).
- Shop files with the same name in different folders, names with spaces and accents, Windows paths: output names are unique and safe. Pinned by `test_outputs.py` (I8); Windows setup in Task I0.

---

### Task I0: Windows environment (Ian, while Eric does F1 to F3)

**Files:** none.

- [ ] **Step 1: Install the tools once**

In PowerShell:

```powershell
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
```

Close and reopen PowerShell, then check `git --version` and `uv --version`. Git for Windows brings Git Bash, which runs the commit hook.

- [ ] **Step 2: Configure git for this repository**

```powershell
git clone <the private repository url> codeml-hackathon
cd codeml-hackathon
git config core.autocrlf false
git config core.longpaths true
git switch dev
```

(`autocrlf false` matters: `.gitattributes` already forces LF so JSON files stay byte-identical on both machines.)

If pushing is not allowed yet, get the repository from Eric as a git bundle instead: `git clone l2c.bundle codeml-hackathon`.

- [ ] **Step 3: Create the environment**

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
uv pip install -e .
```

If PowerShell refuses to run the activation script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

- [ ] **Step 4: Check it works once Eric's F1 to F3 are on dev**

```powershell
python scripts/install_hooks.py
python scripts/check.py
```

Expected: `CHECK PASSED`. Then do Plan 00 Task F4 (mock project and fixtures). Everything below uses only `python -m ...` commands and files, no shell heredocs, so it behaves the same in PowerShell.


---

### Task I1: Matcher: pair plan elements with shop elements

**Files:**
- Create: `backend/l2c/match/__init__.py` (empty), `backend/l2c/match/matcher.py`
- Test: `backend/tests/compare/test_matcher.py`

**Interfaces:**
- Consumes: `ElementExt` (F2), `make_element` (F4).
- Produces: `Pair(plan, shop, method, cost=None, margin=None, extra_shop=[])` with `method` one of `key`, `near_col`, `none`, `unbound`; `match(plan: list[ElementExt], shop: list[ElementExt]) -> list[Pair]`. Exact key `(type, level, row, col)` first; when several shop elements share a key (overlapping shop files) the highest quality one is primary and the rest are kept in `extra_shop`; then a one-to-one assignment on fractional columns (`5.6` vs `6`, distance at most 0.5) with `method="near_col"` and a margin; leftovers become plan-only or shop-only pairs; elements without a grid cell never match (`unbound`). Output order is deterministic.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i1-matcher
```

Create `backend/tests/compare/test_matcher.py`:

```python
from l2c.match.matcher import match
from l2c.mock.elements import make_element


def plan(row, col, **kw):
    return make_element("plan", "N2", row, col, **kw)


def shop(row, col, **kw):
    return make_element("shop", "N2", row, col, **kw)


def test_exact_key_pairs_and_leftovers():
    pairs = match([plan("K", 3), plan("K", 4)], [shop("K", 3), shop("K", 9)])
    by = {(p.plan.grid if p.plan else None, p.shop.grid if p.shop else None): p for p in pairs}
    assert by[("K-3", "K-3")].method == "key"
    assert ("K-4", None) in by and by[("K-4", None)].method == "none"
    assert (None, "K-9") in by


def test_duplicates_pick_the_best_quality_primary_and_keep_the_rest():
    good = shop("K", 3, fichier="DA/Colonnes/A.pdf", overall=0.95)
    weak = shop("K", 3, fichier="DA/Colonnes/B.pdf", overall=0.5)
    (pair,) = match([plan("K", 3)], [weak, good])
    assert pair.shop is good and pair.extra_shop == [weak]


def test_near_column_fallback_for_fractional_gridlines():
    pairs = match([plan("K", 6)], [shop("K", 5.6)])
    (p,) = pairs
    assert p.method == "near_col" and p.shop.grid == "K-5.6" and p.cost == 0.4


def test_near_fallback_respects_the_distance_limit_and_one_to_one():
    pairs = match([plan("K", 3), plan("K", 3.2)], [shop("K", 3.1)])
    assert sorted(p.method for p in pairs) == ["near_col", "none"]
    far = match([plan("K", 3)], [shop("K", 9)])
    assert sorted(p.method for p in far) == ["none", "none"]


def test_unbound_elements_never_match():
    pairs = match([plan(None, None)], [shop(None, None)])
    assert sorted(p.method for p in pairs) == ["unbound", "unbound"]
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_matcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.match'`.

- [ ] **Step 3: Write the matcher**

Create empty `backend/l2c/match/__init__.py`, then:

Create `backend/l2c/match/matcher.py`:

```python
"""Pair plan elements with shop elements by match key (level, grid row, grid column)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from l2c.contract.models import ElementExt

NEAR_COL_MAX = 0.5  # fractional gridlines: 5.6 vs 6 differ by 0.4


@dataclass
class Pair:
    plan: ElementExt | None
    shop: ElementExt | None
    method: str  # key | near_col | none | unbound
    cost: float | None = None
    margin: float | None = None
    extra_shop: list[ElementExt] = field(default_factory=list)


def _complete(e: ElementExt) -> bool:
    k = e.match_key
    return k.row is not None and k.col is not None


def _rank(e: ElementExt) -> tuple[float, str, int, str]:
    return (-e.quality.overall, e.fichier, e.page, e.id)


def match(plan: list[ElementExt], shop: list[ElementExt]) -> list[Pair]:
    pairs: list[Pair] = []
    index: dict[str, list[ElementExt]] = {}
    for e in shop:
        if _complete(e):
            index.setdefault(e.match_key.key_str(), []).append(e)
    for group in index.values():
        group.sort(key=_rank)
    used: set[str] = set()
    pending_plan: list[ElementExt] = []
    for p in sorted(
        plan, key=lambda e: (e.level, e.match_key.row or "", e.match_key.col or 0, e.id)
    ):
        if not _complete(p):
            pairs.append(Pair(p, None, "unbound"))
            continue
        key = p.match_key.key_str()
        if key in index and key not in used:
            primary, *extras = index[key]
            pairs.append(Pair(p, primary, "key", extra_shop=extras))
            used.add(key)
        else:
            pending_plan.append(p)

    free = {k: v for k, v in index.items() if k not in used}
    still_plan: list[ElementExt] = []
    by_group: dict[tuple[str, str, str], list[ElementExt]] = {}
    for p in pending_plan:
        k = p.match_key
        by_group.setdefault((k.type, k.level, k.row or ""), []).append(p)
    free_by_group: dict[tuple[str, str, str], list[str]] = {}
    for key, group in free.items():
        k = group[0].match_key
        free_by_group.setdefault((k.type, k.level, k.row or ""), []).append(key)
    for gk, plist in sorted(by_group.items()):
        shop_keys = sorted(free_by_group.get(gk, []))
        if not shop_keys:
            still_plan.extend(plist)
            continue
        cost = np.array(
            [
                [abs((p.match_key.col or 0) - (free[sk][0].match_key.col or 0)) for sk in shop_keys]
                for p in plist
            ]
        )
        ri, cj = linear_sum_assignment(cost)
        assigned: set[int] = set()
        for i, j in zip(ri, cj, strict=True):
            c = float(cost[i, j])
            if c > NEAR_COL_MAX:
                continue
            others = np.delete(cost[i], j)
            runner = float(others.min()) if others.size else float("inf")
            margin = (
                1.0
                if runner == float("inf")
                else max(0.0, (runner - c) / runner if runner else 0.0)
            )
            primary, *extras = free[shop_keys[j]]
            pairs.append(Pair(plist[i], primary, "near_col", round(c, 3), round(margin, 3), extras))
            used.add(shop_keys[j])
            assigned.add(i)
        still_plan.extend(p for i, p in enumerate(plist) if i not in assigned)
    for p in still_plan:
        pairs.append(Pair(p, None, "none"))
    for key in sorted(k for k in index if k not in used):
        primary, *extras = index[key]
        pairs.append(Pair(None, primary, "none", extra_shop=extras))
    for e in sorted((s for s in shop if not _complete(s)), key=lambda e: (e.fichier, e.page, e.id)):
        pairs.append(Pair(None, e, "unbound"))
    return pairs
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare/test_matcher.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/match backend/tests/compare/test_matcher.py
git commit -m "Add plan to shop matcher"
```

```bash
git switch dev
git merge --no-ff ian/i1-matcher
```


---

### Task I2: Profiles and fusion: trust, status, confidence

**Files:**
- Create: `backend/l2c/compare/__init__.py` (empty), `backend/l2c/compare/profile.py`, `backend/l2c/compare/fusion.py`
- Test: `backend/tests/compare/test_fusion.py`

**Interfaces:**
- Consumes: `ElementExt`, `Diff` and the thresholds in `l2c.contract.constants` (F2); `Pair` (I1).
- Produces: `profile(e) -> Profile(count, size, tie_size, spacing_mm, tie_count)` (positional: `armature[0]` vertical bars, `armature[1]` ties); `profile_diffs(plan, shop) -> list[Diff]` (only fields present on both sides; spacing within `SPACING_TOL_MM`); `armature_groups(e)` and `generic_diffs(plan, shop) -> list[Diff]` (type-agnostic: bar groups matched by bar size); `fusion.match_factor(pair)`, `fusion.trust(plan, shop, pair) -> float` (weaker extraction times match factor), `fusion.decide_pair(rule_fired, trust, anomaly=None, pair_probability=None) -> status`, `fusion.discrepancy_probability(rule_fired, pair_probability=None)`, `fusion.confidence(trust, probability, conforming, anomaly=None)`.
- Rule (spec 10.22): a fired rule with trust at least 0.7 is `non_compliant`; a fired rule with lower trust is `needs_review`; ML or anomaly evidence can only raise a no-difference pair to `needs_review`, never lower a verdict.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i2-fusion
```

Create `backend/tests/compare/test_fusion.py`:

```python
from l2c.compare import fusion
from l2c.contract import constants as C
from l2c.match.matcher import Pair
from l2c.mock.elements import make_element


def pair(method="key", margin=None):
    return Pair(
        make_element("plan", "N2", "K", 3), make_element("shop", "N2", "K", 3), method, None, margin
    )


def test_verdict_needs_both_a_difference_and_enough_trust():
    assert fusion.decide_pair(True, 0.9) == "non_compliant"
    assert fusion.decide_pair(True, C.TRUST_MIN_FOR_VERDICT - 0.01) == "needs_review"
    assert fusion.decide_pair(False, 0.95) == "compliant"
    assert fusion.decide_pair(False, 0.5) == "needs_review"


def test_ml_can_escalate_but_never_suppress():
    assert fusion.decide_pair(False, 0.95, anomaly=0.9) == "needs_review"
    assert fusion.decide_pair(False, 0.95, pair_probability=0.7) == "needs_review"
    assert fusion.decide_pair(False, 0.95, anomaly=0.1, pair_probability=0.1) == "compliant"
    assert fusion.decide_pair(True, 0.95, anomaly=0.0, pair_probability=0.0) == "non_compliant"


def test_near_column_matches_are_trusted_less():
    assert fusion.match_factor(pair("key")) == 1.0
    assert fusion.match_factor(pair("near_col", 1.0)) == 0.7
    assert fusion.match_factor(pair("near_col", 0.0)) < fusion.match_factor(pair("near_col", 1.0))


def test_trust_is_the_weaker_extraction_times_the_match_factor():
    p = Pair(
        make_element("plan", "N2", "K", 3, overall=0.6),
        make_element("shop", "N2", "K", 3, overall=0.9),
        "key",
    )
    assert fusion.trust(p.plan, p.shop, p) == 0.6
    assert fusion.trust(None, None, Pair(None, None, "none")) == 0.0


def test_confidence_and_probability():
    assert fusion.confidence(0.8, 1.0, conforming=False) == 0.8
    assert fusion.confidence(0.8, 0.0, conforming=True) == 0.8
    assert fusion.confidence(0.8, 0.0, conforming=True, anomaly=0.5) == 0.4
    assert (
        fusion.discrepancy_probability(True) == 1.0 and fusion.discrepancy_probability(False) == 0.0
    )
    assert fusion.discrepancy_probability(True, 0.4) == 1.0  # a fired rule is never lowered
    assert fusion.discrepancy_probability(False, 0.4) == 0.4
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_fusion.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.compare'`.

- [ ] **Step 3: Write profile and fusion**

Create empty `backend/l2c/compare/__init__.py`, then:

Create `backend/l2c/compare/profile.py`:

```python
"""Comparable reinforcement profile of a column element, and the diff between two profiles."""

from __future__ import annotations

from dataclasses import dataclass

from l2c.contract import constants as C
from l2c.contract.models import Diff, ElementExt


@dataclass(frozen=True)
class Profile:
    count: int | None
    size: str | None
    tie_size: str | None
    spacing_mm: float | None
    tie_count: int | None


def profile(e: ElementExt) -> Profile:
    vert = e.armature[0] if len(e.armature) > 0 else None
    ties = e.armature[1] if len(e.armature) > 1 else None
    return Profile(
        count=vert.quantite if vert else None,
        size=vert.diametre if vert else None,
        tie_size=ties.diametre if ties else None,
        spacing_mm=ties.espacement_mm if ties else None,
        tie_count=ties.quantite if ties else None,
    )


def profile_diffs(plan: Profile, shop: Profile) -> list[Diff]:
    """Only fields present on both sides are compared (the plan never prints a tie count)."""
    out: list[Diff] = []
    if plan.count is not None and shop.count is not None and plan.count != shop.count:
        out.append(
            Diff(field="count", plan=plan.count, shop=shop.count, delta=shop.count - plan.count)
        )
    if plan.size is not None and shop.size is not None and plan.size != shop.size:
        out.append(Diff(field="size", plan=plan.size, shop=shop.size))
    if plan.tie_size is not None and shop.tie_size is not None and plan.tie_size != shop.tie_size:
        out.append(Diff(field="tie_size", plan=plan.tie_size, shop=shop.tie_size))
    if plan.spacing_mm is not None and shop.spacing_mm is not None:
        delta = round(shop.spacing_mm - plan.spacing_mm, 3)
        if abs(delta) > C.SPACING_TOL_MM:
            out.append(
                Diff(field="spacing_mm", plan=plan.spacing_mm, shop=shop.spacing_mm, delta=delta)
            )
    return out


def armature_groups(e: ElementExt) -> dict[str, list[tuple[int | None, float | None]]]:
    """Bar groups keyed by bar size: [(count, spacing_mm), ...]. Works for any element type."""
    groups: dict[str, list[tuple[int | None, float | None]]] = {}
    for a in e.armature:
        if a.diametre is None:
            continue
        groups.setdefault(a.diametre, []).append((a.quantite, a.espacement_mm))
    for g in groups.values():
        g.sort(key=lambda t: (t[0] if t[0] is not None else -1, t[1] if t[1] is not None else -1.0))
    return groups


def _describe(group: list[tuple[int | None, float | None]]) -> str:
    return ", ".join(
        f"{c if c is not None else '?'} bars" + (f" @{s:g}mm" if s is not None else "")
        for c, s in group
    )


def generic_diffs(plan: ElementExt, shop: ElementExt) -> list[Diff]:
    """Type-agnostic comparison: bar groups matched by bar size, fields compared when both exist."""
    pg, sg = armature_groups(plan), armature_groups(shop)
    out: list[Diff] = []
    for size in sorted(set(pg) | set(sg)):
        if size not in sg:
            out.append(Diff(field=f"bar group {size}", plan=_describe(pg[size]), shop=None))
            continue
        if size not in pg:
            out.append(Diff(field=f"bar group {size}", plan=None, shop=_describe(sg[size])))
            continue
        for (pc, ps), (sc, ss) in zip(pg[size], sg[size], strict=False):
            if pc is not None and sc is not None and pc != sc:
                out.append(Diff(field=f"{size} count", plan=pc, shop=sc, delta=sc - pc))
            if ps is not None and ss is not None and abs(ss - ps) > C.SPACING_TOL_MM:
                out.append(
                    Diff(field=f"{size} spacing_mm", plan=ps, shop=ss, delta=round(ss - ps, 3))
                )
        if len(pg[size]) != len(sg[size]):
            out.append(
                Diff(
                    field=f"{size} group count",
                    plan=len(pg[size]),
                    shop=len(sg[size]),
                    delta=len(sg[size]) - len(pg[size]),
                )
            )
    return out
```

Create `backend/l2c/compare/fusion.py`:

```python
"""Trust, status and confidence (spec 10.22). ML may escalate a verdict, never suppress one."""

from __future__ import annotations

from l2c.contract import constants as C
from l2c.contract.models import ElementExt
from l2c.match.matcher import Pair


def match_factor(pair: Pair) -> float:
    if pair.method == "near_col":
        margin = 1.0 if pair.margin is None else pair.margin
        return round(0.7 * (0.6 + 0.4 * margin), 3)
    return 1.0


def trust(plan: ElementExt | None, shop: ElementExt | None, pair: Pair) -> float:
    overalls = [e.quality.overall for e in (plan, shop) if e is not None]
    return round(min(overalls) * match_factor(pair), 3) if overalls else 0.0


def decide_pair(
    rule_fired: bool,
    trust_value: float,
    anomaly: float | None = None,
    pair_probability: float | None = None,
) -> str:
    """Status for a matched pair: compliant, non_compliant or needs_review."""
    if rule_fired:
        return (
            C.STATUS_NON_COMPLIANT
            if trust_value >= C.TRUST_MIN_FOR_VERDICT
            else C.STATUS_NEEDS_REVIEW
        )
    escalate = (anomaly is not None and anomaly >= C.ANOMALY_ESCALATE) or (
        pair_probability is not None and pair_probability >= C.PAIR_PROB_ESCALATE
    )
    if escalate or trust_value < C.TRUST_MIN_FOR_VERDICT:
        return C.STATUS_NEEDS_REVIEW
    return C.STATUS_COMPLIANT


def discrepancy_probability(rule_fired: bool, pair_probability: float | None = None) -> float:
    if pair_probability is not None:
        return round(max(pair_probability, 1.0 if rule_fired else 0.0), 3)
    return 1.0 if rule_fired else 0.0


def confidence(
    trust_value: float, probability: float, conforming: bool, anomaly: float | None = None
) -> float:
    if conforming:
        return round(trust_value * (1.0 - (anomaly or 0.0)), 3)
    return round(trust_value * probability, 3)
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare/test_fusion.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/compare backend/tests/compare/test_fusion.py
git commit -m "Add profiles and trust fusion"
```

```bash
git switch dev
git merge --no-ff ian/i2-fusion
```


---

### Task I3: `cross.plan_vs_shop` findings

**Files:**
- Create: `backend/l2c/compare/cross.py`
- Test: `backend/tests/compare/test_cross.py`

**Interfaces:**
- Consumes: `Pair` (I1), `profile`/`generic_diffs`/`fusion` (I2), contract models (F2).
- Produces: `compare_pair(pair, plan_levels: set[str], shop_levels: set[str]) -> Finding`; `finding_id(check_type, *parts) -> "F-<12 hex>"` (stable); `ref(element) -> Ref | None`. Statuses: both sides present gives `compliant` / `non_compliant` / `needs_review` (diffs listed with plan and shop values; columns compared by role, every other element type by bar group); plan only gives `missing`, or `needs_review` when the level has no shop data or the block was unbound; shop only gives `added`, or `needs_review` when the level has no plan sheet. A pair without differences but with low trust keeps `confidence = trust` (never 0.0).

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i3-cross
```

Create `backend/tests/compare/test_cross.py`:

```python
from l2c.compare.cross import compare_pair, finding_id
from l2c.match.matcher import Pair
from l2c.mock.elements import make_element

PLAN_LEVELS = {"N2"}
SHOP_LEVELS = {"N2"}


def plan(**kw):
    return make_element("plan", "N2", "K", 3, **kw)


def shop(**kw):
    return make_element("shop", "N2", "K", 3, **kw)


def test_field_diffs_are_listed_with_plan_and_shop_values():
    f = compare_pair(
        Pair(plan(count=4), shop(count=6, spacing_mm=304.8), "key"), PLAN_LEVELS, SHOP_LEVELS
    )
    assert f.status == "non_compliant"
    assert {(d.field, d.plan, d.shop) for d in f.diffs} == {
        ("count", 4, 6),
        ("spacing_mm", 152.4, 304.8),
    }
    assert f.plan_ref.element_id and f.shop_ref.element_id and f.evidence.rule.fired


def test_a_missing_or_added_element_needs_trust_and_coverage():
    missing = compare_pair(Pair(plan(), None, "none"), PLAN_LEVELS, SHOP_LEVELS)
    assert missing.status == "missing" and missing.shop_ref is None
    not_covered = compare_pair(Pair(plan(), None, "none"), PLAN_LEVELS, {"N9"})
    assert not_covered.status == "needs_review" and "no shop data" in not_covered.notes
    added = compare_pair(Pair(None, shop(), "none"), PLAN_LEVELS, SHOP_LEVELS)
    assert added.status == "added" and added.plan_ref is None
    weak = compare_pair(Pair(None, shop(overall=0.3), "none"), PLAN_LEVELS, SHOP_LEVELS)
    assert weak.status == "needs_review"


def test_unbound_blocks_are_never_called_missing():
    f = compare_pair(
        Pair(make_element("plan", "N2", None, None), None, "unbound"), PLAN_LEVELS, SHOP_LEVELS
    )
    assert f.status == "needs_review" and f.evidence.rule.kind == "unbound_plan_block"


def test_finding_ids_are_stable_and_distinguish_the_pair():
    assert finding_id("a", "p1", "s1") == finding_id("a", "p1", "s1")
    assert finding_id("a", "p1", "s1") != finding_id("a", "p1", "s2")
    assert finding_id("a", None, "s1").startswith("F-")
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_cross.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.compare.cross'`.

- [ ] **Step 3: Write the comparator**

Create `backend/l2c/compare/cross.py`:

```python
"""cross.plan_vs_shop: one finding per match pair (compliant, non_compliant, missing, added)."""

from __future__ import annotations

import hashlib

from l2c.compare import fusion
from l2c.compare.profile import generic_diffs, profile, profile_diffs
from l2c.contract import constants as C
from l2c.contract.models import (
    ElementExt,
    Evidence,
    ExtractionEvidence,
    Finding,
    MatchEvidence,
    Ref,
    RuleEvidence,
)
from l2c.match.matcher import Pair


def ref(e: ElementExt | None) -> Ref | None:
    if e is None:
        return None
    return Ref(element_id=e.id, fichier=e.fichier, page=e.page, x=e.x, y=e.y)


def finding_id(check_type: str, *parts: str | None) -> str:
    raw = "|".join([check_type, *[p or "" for p in parts]])
    return "F-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def compare_pair(pair: Pair, plan_levels: set[str], shop_levels: set[str]) -> Finding:
    plan, shop = pair.plan, pair.shop
    anchor = plan or shop
    assert anchor is not None
    key = anchor.match_key
    t = fusion.trust(plan, shop, pair)
    notes = ""
    diffs = []
    kind = "field_diff"
    if plan and shop:
        diffs = (
            profile_diffs(profile(plan), profile(shop))
            if key.type == "colonne"
            else generic_diffs(plan, shop)
        )
        fired = bool(diffs)
        status = fusion.decide_pair(fired, t)
        conforming = not fired  # no difference found; low trust only lowers the confidence
    elif plan:
        kind = "missing"
        fired = True
        if pair.method == "unbound":
            kind, status, notes = (
                "unbound_plan_block",
                C.STATUS_NEEDS_REVIEW,
                "block not bound to a grid cell",
            )
        elif plan.level not in shop_levels:
            kind, status, notes = (
                "level_not_covered",
                C.STATUS_NEEDS_REVIEW,
                "no shop data for this level",
            )
        else:
            status = C.STATUS_MISSING if t >= C.TRUST_MIN_FOR_VERDICT else C.STATUS_NEEDS_REVIEW
        conforming = False
    else:
        assert shop is not None
        kind = "added"
        fired = True
        if pair.method == "unbound":
            kind, status, notes = (
                "unbound_shop_block",
                C.STATUS_NEEDS_REVIEW,
                "block not bound to a grid cell",
            )
        elif shop.level not in plan_levels:
            kind, status, notes = (
                "level_not_covered",
                C.STATUS_NEEDS_REVIEW,
                "level has no plan sheet in scope",
            )
        else:
            status = C.STATUS_ADDED if t >= C.TRUST_MIN_FOR_VERDICT else C.STATUS_NEEDS_REVIEW
        conforming = False
    prob = fusion.discrepancy_probability(fired and not conforming)
    return Finding(
        id=finding_id(
            "cross.plan_vs_shop", plan.id if plan else None, shop.id if shop else None, kind
        ),
        check_type="cross.plan_vs_shop",
        status=status,  # type: ignore[arg-type]
        type_element=key.type,
        level=key.level,
        grid=anchor.grid,
        plan_ref=ref(plan),
        shop_ref=ref(shop),
        diffs=diffs,
        evidence=Evidence(
            rule=RuleEvidence(fired=fired and not conforming, kind=kind, diffs=diffs),
            extraction=ExtractionEvidence(
                plan_overall=plan.quality.overall if plan else None,
                shop_overall=shop.quality.overall if shop else None,
                flags=sorted(
                    {*(plan.quality.flags if plan else []), *(shop.quality.flags if shop else [])}
                ),
            ),
            match=MatchEvidence(
                method=pair.method, assignment_cost=pair.cost, margin_to_runner_up=pair.margin
            ),
        ),
        trust=t,
        discrepancy_probability=prob,
        confidence=fusion.confidence(t, prob, conforming),
        notes=notes,
    )
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare/test_cross.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/compare/cross.py backend/tests/compare/test_cross.py
git commit -m "Add plan vs shop comparison"
```

```bash
git switch dev
git merge --no-ff ian/i3-cross
```


---

### Task I4: Self checks: peer outliers, internal consistency, plausibility

**Files:**
- Create: `backend/l2c/compare/self_checks.py`
- Test: `backend/tests/compare/test_self_checks.py`

**Interfaces:**
- Consumes: `profile`, `fusion` (I2), `finding_id`, `ref` (I3), `LevelInfo`, contract models.
- Produces: `peer_outliers(elements) -> list[Outlier(element, field, value, mode, score)]` (per sheet and level; a value is an outlier when it is rare among peers while the peers agree: group of at least `PEER_MIN_GROUP`, mode share at least 0.6, own share at most 0.1; score `mode_share * (1 - share)`); `outlier_finding(o) -> Finding` (`self.peer_outlier`, `needs_review`, `evidence.ml.peer_anomaly`); `storey_heights(levels)`; `tie_ratios(elements, heights)`; `learned_band(ratios) -> (lo, hi, "learned"|"fallback")` (median plus or minus 6 robust sigmas of the project's own tie count times spacing over storey height, with a fixed fallback below 20 samples; measured 0.96 to 1.21 on the CLP development project); `internal_consistency_findings(elements, levels)`; `plausibility_findings(elements)` (elements whose extraction sanity checks failed).

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i4-self
```

Create `backend/tests/compare/test_self_checks.py`:

```python
from l2c.compare.self_checks import (
    internal_consistency_findings,
    learned_band,
    peer_outliers,
    plausibility_findings,
    storey_heights,
)
from l2c.contract import constants as C
from l2c.contract.models import LevelInfo
from l2c.mock.elements import make_element

LEVELS = [
    LevelInfo(level="N2", name="N2", elevation_mm=0.0),
    LevelInfo(level="N3", name="N3", elevation_mm=3500.0),
]


def plan_row(n, **odd):
    return [
        make_element("plan", "N2", "K", c, x=100.0 + c, **(odd if c == 3 else {}))
        for c in range(1, n + 1)
    ]


def test_a_rare_value_among_agreeing_peers_is_an_outlier_with_a_high_score():
    out = peer_outliers(plan_row(12, size="35M"))
    assert [(o.field, o.value, o.mode) for o in out] == [("size", "35M", "25M")]
    assert out[0].score > 0.8 and out[0].element.grid == "K-3"


def test_no_outlier_when_peers_disagree_or_the_group_is_small():
    mixed = [
        make_element("plan", "N2", "K", c, size="25M" if c % 2 else "35M") for c in range(1, 13)
    ]
    assert peer_outliers(mixed) == []
    assert peer_outliers(plan_row(C.PEER_MIN_GROUP - 1, size="35M")) == []


def test_groups_are_per_sheet_and_level():
    elements = plan_row(12) + [make_element("plan", "N3", "K", c, size="35M") for c in range(1, 13)]
    assert peer_outliers(elements) == []  # N3 is uniformly 35M, N2 uniformly 25M


def test_storey_heights_come_from_consecutive_levels():
    assert storey_heights(LEVELS) == {"N2": 3500.0}


def test_learned_band_adapts_to_the_projects_own_data_and_falls_back_when_small():
    assert learned_band([1.0] * 5)[2] == "fallback"
    lo, hi, how = learned_band([1.0] * 30)
    assert how == "learned" and lo < 1.0 < hi
    lo2, hi2, _ = learned_band([1.6] * 30)  # a project that is consistently different
    assert lo2 < 1.6 < hi2


def test_internal_consistency_flags_an_impossible_tie_count_only():
    ok = [make_element("shop", "N2", "K", c, tie_count=23, x=100.0 + c) for c in range(1, 25)]
    bad = make_element("shop", "N2", "L", 1, tie_count=60)
    out = internal_consistency_findings([*ok, bad], LEVELS)
    assert [f.grid for f in out] == ["L-1"] and out[0].status == "needs_review"
    assert internal_consistency_findings(ok, []) == []  # no elevations: nothing to check


def test_plausibility_reports_failed_extraction_checks():
    e = make_element("plan", "N2", "K", 3)
    bad = e.model_copy(
        update={
            "quality": e.quality.model_copy(update={"consistency_failed": ["size_in_vocabulary"]})
        }
    )
    out = plausibility_findings([e, bad])
    assert len(out) == 1 and "size_in_vocabulary" in out[0].notes
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_self_checks.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.compare.self_checks'`.

- [ ] **Step 3: Write the checks**

Create `backend/l2c/compare/self_checks.py`:

```python
"""Checks of one metadata file against itself: peer outliers, internal consistency, plausibility."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

from l2c.compare import fusion
from l2c.compare.cross import finding_id, ref
from l2c.compare.profile import profile
from l2c.contract import constants as C
from l2c.contract.models import (
    Diff,
    ElementExt,
    Evidence,
    ExtractionEvidence,
    Finding,
    LevelInfo,
    MlEvidence,
    RuleEvidence,
)

PEER_FIELDS = ("count", "size", "tie_size", "spacing_mm")


@dataclass(frozen=True)
class Outlier:
    element: ElementExt
    field: str
    value: float | int | str
    mode: float | int | str
    score: float


def peer_outliers(elements: list[ElementExt]) -> list[Outlier]:
    """Elements with a value rare among peers (same sheet and level) when the peers agree."""
    groups: dict[tuple[str, str, int, str], list[ElementExt]] = {}
    for e in elements:
        groups.setdefault((e.source, e.fichier, e.page, e.level), []).append(e)
    found: list[Outlier] = []
    for _, members in sorted(groups.items()):
        if len(members) < C.PEER_MIN_GROUP:
            continue
        for field in PEER_FIELDS:
            values = [(e, getattr(profile(e), field)) for e in members]
            values = [(e, v) for e, v in values if v is not None]
            if len(values) < C.PEER_MIN_GROUP:
                continue
            counts = Counter(v for _, v in values)
            mode, mode_n = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[0]
            mode_share = mode_n / len(values)
            if mode_share < C.PEER_MODE_SHARE_MIN:
                continue
            for e, v in values:
                share = counts[v] / len(values)
                if v != mode and share <= C.PEER_RARE_SHARE_MAX:
                    found.append(Outlier(e, field, v, mode, round(mode_share * (1 - share), 3)))
    return sorted(found, key=lambda o: (o.element.id, o.field))


def outlier_finding(o: Outlier) -> Finding:
    e = o.element
    t = e.quality.overall
    return Finding(
        id=finding_id("self.peer_outlier", e.id, o.field),
        check_type="self.peer_outlier",
        status=C.STATUS_NEEDS_REVIEW,  # type: ignore[arg-type]
        type_element=e.match_key.type,
        level=e.level,
        grid=e.grid,
        plan_ref=ref(e) if e.source == "plan" else None,
        shop_ref=ref(e) if e.source == "shop" else None,
        diffs=[Diff(field=f"{o.field} (value vs peer mode)", plan=o.value, shop=o.mode)],
        evidence=Evidence(
            rule=RuleEvidence(fired=False, kind="peer_outlier"),
            extraction=ExtractionEvidence(
                plan_overall=t if e.source == "plan" else None,
                shop_overall=t if e.source == "shop" else None,
                flags=list(e.quality.flags),
            ),
            ml=MlEvidence(peer_anomaly=o.score, model_version="mode-share-v1"),
        ),
        trust=t,
        discrepancy_probability=o.score,
        confidence=fusion.confidence(t, o.score, conforming=False),
        notes=f"{o.field} differs from {o.mode!r} used by most peers on this sheet",
    )


def storey_heights(levels: list[LevelInfo]) -> dict[str, float]:
    ordered = sorted(
        (lv for lv in levels if lv.elevation_mm is not None), key=lambda lv: lv.elevation_mm or 0.0
    )
    return {
        lo.level: (hi.elevation_mm or 0.0) - (lo.elevation_mm or 0.0)
        for lo, hi in zip(ordered, ordered[1:], strict=False)
    }


def tie_ratios(elements: list[ElementExt], heights: dict[str, float]) -> dict[str, float]:
    """tie count x spacing / storey height for every shop element that has all three."""
    out: dict[str, float] = {}
    for e in elements:
        if e.source != "shop":
            continue
        p = profile(e)
        h = heights.get(e.level)
        if h and p.tie_count is not None and p.spacing_mm is not None:
            out[e.id] = round(p.tie_count * p.spacing_mm / h, 3)
    return out


def learned_band(ratios: list[float]) -> tuple[float, float, str]:
    """Accepted ratio band from the project's own data; fixed fallback when too few samples."""
    if len(ratios) < C.TIE_BAND_MIN_SAMPLES:
        return C.TIE_RATIO_MIN, C.TIE_RATIO_MAX, "fallback"
    med = statistics.median(ratios)
    mad = statistics.median(abs(r - med) for r in ratios)
    sigma = max(1.4826 * mad, C.TIE_BAND_SIGMA_FLOOR * med)
    return med - C.TIE_BAND_K * sigma, med + C.TIE_BAND_K * sigma, "learned"


def internal_consistency_findings(
    elements: list[ElementExt], levels: list[LevelInfo]
) -> list[Finding]:
    """Ties are spread over the storey: tie count x spacing is about the storey height."""
    ratios = tie_ratios(elements, storey_heights(levels))
    if not ratios:
        return []
    lo, hi, how = learned_band(list(ratios.values()))
    by_id = {e.id: e for e in elements}
    out: list[Finding] = []
    for element_id, ratio in sorted(ratios.items()):
        if lo <= ratio <= hi:
            continue
        e = by_id[element_id]
        t = e.quality.overall
        out.append(
            Finding(
                id=finding_id("self.internal_consistency", e.id),
                check_type="self.internal_consistency",
                status=C.STATUS_NEEDS_REVIEW,  # type: ignore[arg-type]
                type_element=e.match_key.type,
                level=e.level,
                grid=e.grid,
                shop_ref=ref(e),
                diffs=[
                    Diff(
                        field="tie_count*spacing/height",
                        plan=f"{lo:.2f}-{hi:.2f} ({how} band)",
                        shop=ratio,
                    )
                ],
                evidence=Evidence(
                    rule=RuleEvidence(fired=True, kind="internal_consistency"),
                    extraction=ExtractionEvidence(shop_overall=t, flags=list(e.quality.flags)),
                ),
                trust=t,
                discrepancy_probability=1.0,
                confidence=fusion.confidence(t, 1.0, conforming=False),
                notes="tie count and spacing do not fit the storey height",
            )
        )
    return out


def plausibility_findings(elements: list[ElementExt]) -> list[Finding]:
    out: list[Finding] = []
    for e in elements:
        failed = e.quality.consistency_failed
        if not failed:
            continue
        t = e.quality.overall
        out.append(
            Finding(
                id=finding_id("self.plausibility", e.id),
                check_type="self.plausibility",
                status=C.STATUS_NEEDS_REVIEW,  # type: ignore[arg-type]
                type_element=e.match_key.type,
                level=e.level,
                grid=e.grid,
                plan_ref=ref(e) if e.source == "plan" else None,
                shop_ref=ref(e) if e.source == "shop" else None,
                evidence=Evidence(
                    rule=RuleEvidence(fired=True, kind="plausibility"),
                    extraction=ExtractionEvidence(
                        plan_overall=t if e.source == "plan" else None,
                        shop_overall=t if e.source == "shop" else None,
                        flags=list(failed),
                    ),
                ),
                trust=t,
                discrepancy_probability=1.0,
                confidence=fusion.confidence(t, 1.0, conforming=False),
                notes="failed sanity checks: " + ", ".join(failed),
            )
        )
    return out
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare/test_self_checks.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/compare/self_checks.py backend/tests/compare/test_self_checks.py
git commit -m "Add peer outlier and consistency checks"
```

```bash
git switch dev
git merge --no-ff ian/i4-self
```


---

### Task I5: Duplicate and cross-file conflicts

**Files:**
- Create: `backend/l2c/compare/duplicates.py`
- Test: `backend/tests/compare/test_duplicates.py`

**Interfaces:**
- Consumes: `profile`, `profile_diffs` (I2), `finding_id`, `ref` (I3).
- Produces: `duplicate_findings(elements) -> list[Finding]`: the same element (same source and match key) annotated twice with different values gives `cross.shop_vs_shop` (two shop files) or `self.duplicate` (same file), status `needs_review`; identical duplicates (overlapping files such as Parts 2 and 3 on CLP) give nothing; unbound elements are ignored.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i5-duplicates
```

Create `backend/tests/compare/test_duplicates.py`:

```python
from l2c.compare.duplicates import duplicate_findings
from l2c.mock.elements import make_element


def shop(file, **kw):
    return make_element("shop", "N2", "K", 3, fichier=file, **kw)


def test_conflicting_values_in_two_shop_files_are_a_cross_file_finding():
    out = duplicate_findings(
        [shop("DA/Colonnes/A.pdf", count=4), shop("DA/Colonnes/B.pdf", count=6)]
    )
    assert [(f.check_type, f.status) for f in out] == [("cross.shop_vs_shop", "needs_review")]
    assert out[0].diffs[0].field == "count"


def test_identical_duplicates_are_harmless():
    assert duplicate_findings([shop("DA/Colonnes/A.pdf"), shop("DA/Colonnes/B.pdf")]) == []


def test_conflict_inside_one_file_is_a_plain_duplicate():
    out = duplicate_findings(
        [shop("DA/Colonnes/A.pdf", count=4, page=1), shop("DA/Colonnes/A.pdf", count=6, page=2)]
    )
    assert [f.check_type for f in out] == ["self.duplicate"]


def test_unbound_elements_and_different_cells_are_ignored():
    a = make_element("shop", "N2", None, None)
    b = make_element("shop", "N2", None, None, x=5.0)
    c = make_element("shop", "N2", "K", 4, fichier="DA/Colonnes/B.pdf")
    assert duplicate_findings([a, b, shop("DA/Colonnes/A.pdf"), c]) == []
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_duplicates.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.compare.duplicates'`.

- [ ] **Step 3: Write the check**

Create `backend/l2c/compare/duplicates.py`:

```python
"""The same element annotated twice with different values (across shop files, or on one sheet)."""

from __future__ import annotations

from l2c.compare import fusion
from l2c.compare.cross import finding_id, ref
from l2c.compare.profile import profile, profile_diffs
from l2c.contract import constants as C
from l2c.contract.models import ElementExt, Evidence, ExtractionEvidence, Finding, RuleEvidence


def duplicate_findings(elements: list[ElementExt]) -> list[Finding]:
    groups: dict[tuple[str, str], list[ElementExt]] = {}
    for e in elements:
        k = e.match_key
        if k.row is None or k.col is None:
            continue
        groups.setdefault((e.source, k.key_str()), []).append(e)
    out: list[Finding] = []
    for (source, _), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        members.sort(key=lambda e: (e.fichier, e.page, e.id))
        first = members[0]
        for other in members[1:]:
            diffs = profile_diffs(profile(first), profile(other))
            if not diffs:
                continue  # an identical duplicate is harmless
            cross_file = first.fichier != other.fichier
            check = "cross.shop_vs_shop" if (source == "shop" and cross_file) else "self.duplicate"
            t = round(min(first.quality.overall, other.quality.overall), 3)
            out.append(
                Finding(
                    id=finding_id(check, first.id, other.id),
                    check_type=check,  # type: ignore[arg-type]
                    status=C.STATUS_NEEDS_REVIEW,  # type: ignore[arg-type]
                    type_element=first.match_key.type,
                    level=first.level,
                    grid=first.grid,
                    plan_ref=ref(first) if source == "plan" else None,
                    shop_ref=ref(other) if source == "shop" else None,
                    diffs=diffs,
                    evidence=Evidence(
                        rule=RuleEvidence(fired=True, kind="duplicate_conflict", diffs=diffs),
                        extraction=ExtractionEvidence(
                            plan_overall=first.quality.overall if source == "plan" else None,
                            shop_overall=t if source == "shop" else None,
                        ),
                    ),
                    trust=t,
                    discrepancy_probability=1.0,
                    confidence=fusion.confidence(t, 1.0, conforming=False),
                    notes=(
                        f"{first.fichier} p{first.page} and {other.fichier} p{other.page} disagree"
                    ),
                )
            )
    return out
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare/test_duplicates.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/compare/duplicates.py backend/tests/compare/test_duplicates.py
git commit -m "Add duplicate conflict check"
```

```bash
git switch dev
git merge --no-ff ian/i5-duplicates
```


---

### Task I6: `run_comparison` and the golden tests

**Files:**
- Create: `backend/l2c/compare/run.py`
- Test: `backend/tests/compare/test_golden.py`, `backend/tests/compare/test_generic.py`, `backend/tests/compare/test_fixtures_golden.py`

**Interfaces:**
- Consumes: I1 to I5, `MetaBundle` (F2), the committed fixtures (F4).
- Produces: `run_comparison(bundle: MetaBundle, use_ml: bool = False) -> list[Finding]` (pure and deterministic; sorted by level, grid, check type, id); `add_pair_probabilities(findings, bundle)` and `MIN_PAIRS_TO_LEARN = 50` (used by Task I9; `use_ml=False` here).
- Golden contract: running the comparison on `mock_project()` and on the committed `shared/fixtures/mock_a/metadata` must produce exactly the findings listed in `expected_findings.json`, nothing more, nothing less.

- [ ] **Step 1: Branch and write the failing tests**

```bash
git switch dev
git pull
git switch -c ian/i6-run
```

Create `backend/tests/compare/test_golden.py`:

```python
from l2c.compare.run import run_comparison
from l2c.mock.generate import mock_project


def test_mock_project_produces_exactly_the_expected_findings():
    m = mock_project()
    findings = run_comparison(m.bundle)
    got = {(f.check_type, f.status, f.level, f.grid) for f in findings if f.status != "compliant"}
    want = {(x.check_type, x.status, x.level, x.grid) for x in m.expected}
    assert got == want, {"unexpected": got - want, "missing": want - got}


def test_compliant_pairs_are_reported_with_full_trust():
    findings = run_comparison(mock_project().bundle)
    ok = [f for f in findings if f.status == "compliant"]
    assert len(ok) > 10
    assert all(f.check_type == "cross.plan_vs_shop" and f.confidence >= 0.9 for f in ok)


def test_low_trust_difference_is_not_a_firm_verdict():
    findings = run_comparison(mock_project().bundle)
    f = next(
        x
        for x in findings
        if x.grid == "K-4" and x.level == "N3" and x.check_type == "cross.plan_vs_shop"
    )
    assert f.status == "needs_review" and f.evidence.rule.fired and f.diffs[0].field == "count"
    assert f.trust == 0.4 and f.confidence == 0.4


def test_peer_outlier_and_cross_finding_agree_on_the_known_case():
    findings = run_comparison(mock_project().bundle)
    here = [f for f in findings if f.grid == "K-6" and f.level == "N2"]
    kinds = {(f.check_type, f.status) for f in here}
    assert ("cross.plan_vs_shop", "non_compliant") in kinds
    assert ("self.peer_outlier", "needs_review") in kinds
    outlier = next(f for f in here if f.check_type == "self.peer_outlier")
    assert outlier.evidence.ml and outlier.evidence.ml.peer_anomaly > 0.8


def test_findings_are_deterministic_and_have_unique_ids():
    a = run_comparison(mock_project().bundle)
    b = run_comparison(mock_project().bundle)
    assert [f.model_dump_json() for f in a] == [f.model_dump_json() for f in b]
    assert len({f.id for f in a}) == len(a)


def test_a_pair_without_differences_but_low_trust_keeps_a_meaningful_confidence():
    from l2c.compare.run import run_comparison
    from l2c.contract.io import MetaBundle
    from l2c.mock.elements import make_element

    plan = make_element("plan", "N2", "K", 3, overall=0.6)
    shop = make_element("shop", "N2", "K", 3, overall=0.9)
    (f,) = [
        x
        for x in run_comparison(MetaBundle(project="x", elements=[plan, shop]))
        if x.check_type == "cross.plan_vs_shop"
    ]
    assert f.status == "needs_review" and not f.evidence.rule.fired
    assert f.trust == 0.6 and f.confidence == 0.6  # not 0.0
```

Create `backend/tests/compare/test_generic.py`:

```python
from l2c.compare.run import run_comparison
from l2c.contract.io import MetaBundle
from l2c.contract.models import Armature
from l2c.mock.elements import make_element


def slab(source, *, groups, col=3):
    return make_element(
        source,
        "N2",
        "K",
        col,
        type_element="dalle",
        armature=[
            Armature(repere=f"B{i}", diametre=d, quantite=c, espacement_mm=s)
            for i, (d, c, s) in enumerate(groups)
        ],
    )


def statuses(plan, shop):
    bundle = MetaBundle(project="x", elements=[*plan, *shop])
    return [
        (f.check_type, f.status, [d.field for d in f.diffs])
        for f in run_comparison(bundle)
        if f.check_type == "cross.plan_vs_shop"
    ]


def test_other_element_types_compare_by_bar_group_not_by_column_layout():
    same = [("15M", 16, None), ("10M", None, 300.0)]
    assert statuses([slab("plan", groups=same)], [slab("shop", groups=same)])[0][1] == "compliant"
    diff = statuses(
        [slab("plan", groups=same)],
        [slab("shop", groups=[("15M", 20, None), ("10M", None, 300.0)])],
    )
    assert diff == [("cross.plan_vs_shop", "non_compliant", ["15M count"])]


def test_missing_and_extra_bar_groups_are_reported():
    out = statuses(
        [slab("plan", groups=[("15M", 16, None), ("20M", 8, None)])],
        [slab("shop", groups=[("15M", 16, None), ("25M", 4, None)])],
    )
    assert out[0][1] == "non_compliant"
    assert sorted(out[0][2]) == ["bar group 20M", "bar group 25M"]


def test_spacing_within_tolerance_is_not_a_difference():
    a = [slab("plan", groups=[("10M", None, 152.4)])]
    b = [slab("shop", groups=[("10M", None, 152.9)])]
    assert statuses(a, b)[0][1] == "compliant"
```

Create `backend/tests/compare/test_fixtures_golden.py`:

```python
"""The committed fixtures are the shared contract: the comparison must reproduce their expected
findings. Either lane breaking this has broken the contract."""

import json
from pathlib import Path

from l2c.compare.run import run_comparison
from l2c.contract.io import read_bundle

FIX = Path(__file__).resolve().parents[3] / "shared" / "fixtures" / "mock_a"


def test_comparison_on_the_committed_fixtures_matches_expected_findings():
    bundle = read_bundle(FIX / "metadata")
    expected = json.loads((FIX / "expected_findings.json").read_text(encoding="utf-8"))
    want = {(x["check_type"], x["status"], x["level"], x["grid"]) for x in expected}
    got = {
        (f.check_type, f.status, f.level, f.grid)
        for f in run_comparison(bundle)
        if f.status != "compliant"
    }
    assert got == want, {"unexpected": got - want, "missing": want - got}
```

- [ ] **Step 2: Run them to verify they fail**

```powershell
python -m pytest backend/tests/compare/test_golden.py backend/tests/compare/test_generic.py backend/tests/compare/test_fixtures_golden.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.compare.run'`.

- [ ] **Step 3: Write the runner**

Create `backend/l2c/compare/run.py`:

```python
"""Run every comparison on a metadata bundle. Pure function of the bundle; deterministic."""

from __future__ import annotations

from l2c.compare import fusion
from l2c.compare.cross import compare_pair
from l2c.compare.duplicates import duplicate_findings
from l2c.compare.self_checks import (
    internal_consistency_findings,
    outlier_finding,
    peer_outliers,
    plausibility_findings,
)
from l2c.contract import constants as C
from l2c.contract.io import MetaBundle
from l2c.contract.models import Finding, MlEvidence
from l2c.match.matcher import match

MIN_PAIRS_TO_LEARN = 50  # below this the project is too small to train a model on itself


def add_pair_probabilities(findings: list[Finding], bundle: MetaBundle) -> list[Finding]:
    """Attach a learned probability to every matched pair, trained on this project's own pairs.

    No labels are needed: the model learns from mutations of the project's agreeing pairs and
    from the project's own weak-extraction flags (see compare/ml/dataset.py). The statuses it may
    change are limited to *raising* a no-difference pair to needs_review; a deterministic
    non_compliant/missing/added verdict is never lowered.
    """
    from l2c.compare.ml import pair_model
    from l2c.compare.ml.dataset import build_dataset_from_bundle

    agreeing = [
        f
        for f in findings
        if f.check_type == "cross.plan_vs_shop"
        and f.plan_ref
        and f.shop_ref
        and not f.evidence.rule.fired
    ]
    if len(agreeing) < MIN_PAIRS_TO_LEARN:
        return findings
    X, y = build_dataset_from_bundle(bundle)
    if len(set(y)) < 2:
        return findings
    model = pair_model.train(X, y)
    out: list[Finding] = []
    for f in findings:
        if f.check_type != "cross.plan_vs_shop" or not (f.plan_ref and f.shop_ref):
            out.append(f)
            continue
        prob = model.predict(f)
        fired = f.evidence.rule.fired
        status = f.status
        if not fired and status == C.STATUS_COMPLIANT:
            status = fusion.decide_pair(False, f.trust, None, prob)
        discrepancy = fusion.discrepancy_probability(fired, prob)
        conforming = not fired and status == C.STATUS_COMPLIANT
        ml = MlEvidence(pair_probability=round(prob, 3), model_version=model.version)
        out.append(
            f.model_copy(
                update={
                    "status": status,
                    "discrepancy_probability": discrepancy,
                    "confidence": fusion.confidence(f.trust, discrepancy, conforming),
                    "evidence": f.evidence.model_copy(update={"ml": ml}),
                }
            )
        )
    return out


def run_comparison(bundle: MetaBundle, use_ml: bool = False) -> list[Finding]:
    plan = [e for e in bundle.elements if e.source == "plan"]
    shop = [e for e in bundle.elements if e.source == "shop"]
    plan_levels = {e.level for e in plan}
    shop_levels = {e.level for e in shop}
    findings: list[Finding] = [compare_pair(p, plan_levels, shop_levels) for p in match(plan, shop)]
    if use_ml:
        findings = add_pair_probabilities(findings, bundle)
    findings += [outlier_finding(o) for o in peer_outliers(bundle.elements)]
    findings += internal_consistency_findings(bundle.elements, bundle.levels)
    findings += plausibility_findings(bundle.elements)
    findings += duplicate_findings(bundle.elements)
    return sorted(findings, key=lambda f: (f.level, f.grid or "", f.check_type, f.id))
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare -v
```

Expected: all tests in the folder pass (golden 6, generic 3, fixtures golden 1, plus the earlier tasks). `test_a_pair_without_differences_but_low_trust_keeps_a_meaningful_confidence` pins the confidence rule; `test_other_element_types_compare_by_bar_group_not_by_column_layout` proves non-column types compare correctly.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/compare/run.py backend/tests/compare
git commit -m "Add run_comparison and golden tests"
```

```bash
git switch dev
git merge --no-ff ian/i6-run
```


---

### Task I7: Fuzz: random projects with injected defects

**Files:**
- Create: `backend/l2c/mock/fuzz.py`
- Test: `backend/tests/compare/test_fuzz.py`

**Interfaces:**
- Consumes: `make_element` (F4), `run_comparison` (I6).
- Produces: `fuzz_project(seed) -> FuzzProject(bundle, injected)`; each seed varies the number and names of levels and their heights, grid rows and columns (some fractional), the number of shop files, the bar size, tie size, tie spacing and bar count, and injects 3 to 6 defects of kind `count`, `size`, `spacing`, `tie_size`, `missing` or `added` with known ground truth.

The test requires, for 60 seeds: every injected defect appears as `non_compliant` / `missing` / `added` at its level and grid cell, **and nothing else** is flagged by `cross.plan_vs_shop` (precision), plus total recall of 1.0 over more than 150 defects.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i7-fuzz
```

Create `backend/tests/compare/test_fuzz.py`:

```python
import pytest

from l2c.compare.run import run_comparison
from l2c.mock.fuzz import fuzz_project

SEEDS = range(60)


@pytest.mark.parametrize("seed", SEEDS)
def test_every_injected_defect_is_found_and_nothing_else_is_flagged(seed):
    fp = fuzz_project(seed)
    findings = [f for f in run_comparison(fp.bundle) if f.check_type == "cross.plan_vs_shop"]
    got = {(f.level, f.grid): f.status for f in findings if f.status != "compliant"}
    want = {(i.level, i.grid): i.expected_status for i in fp.injected}
    assert got == want, {
        "seed": seed,
        "unexpected": got.keys() - want.keys(),
        "missed": want.keys() - got.keys(),
        "wrong": {k: (got[k], want[k]) for k in got.keys() & want.keys() if got[k] != want[k]},
    }


def test_fuzz_projects_really_vary():
    shapes = {
        (
            len(fp.bundle.levels),
            len({e.match_key.row for e in fp.bundle.elements}),
            len({e.fichier for e in fp.bundle.elements if e.source == "shop"}),
        )
        for fp in map(fuzz_project, SEEDS)
    }
    assert len(shapes) >= 10


def test_recall_over_all_seeds_is_one():
    found = total = 0
    for seed in SEEDS:
        fp = fuzz_project(seed)
        flagged = {
            (f.level, f.grid)
            for f in run_comparison(fp.bundle)
            if f.check_type == "cross.plan_vs_shop" and f.status != "compliant"
        }
        total += len(fp.injected)
        found += sum((i.level, i.grid) in flagged for i in fp.injected)
    assert total > 150 and found == total
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_fuzz.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.mock.fuzz'`.

- [ ] **Step 3: Write the generator**

Create `backend/l2c/mock/fuzz.py`:

```python
"""Random synthetic projects with injected defects: proves the comparison does not depend on one
project's shape (levels, grid size, bar sizes, spacings, file layout all vary with the seed)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from l2c.contract.constants import BAR_SIZES
from l2c.contract.io import MetaBundle
from l2c.contract.models import ElementExt, LevelInfo
from l2c.mock.elements import make_element

LEVEL_POOL = ("SS", "RDC", "N2", "N3", "N4", "N5", "N6")
ROW_POOL = "ABCDEFGHJKLMN"
SPACINGS_MM = (101.6, 152.4, 203.2, 304.8)
DEFECT_KINDS = ("count", "size", "spacing", "tie_size", "missing", "added")
EXPECTED_STATUS = {
    "count": "non_compliant",
    "size": "non_compliant",
    "spacing": "non_compliant",
    "tie_size": "non_compliant",
    "missing": "missing",
    "added": "added",
}


@dataclass(frozen=True)
class Injected:
    kind: str
    level: str
    grid: str

    @property
    def expected_status(self) -> str:
        return EXPECTED_STATUS[self.kind]


@dataclass
class FuzzProject:
    bundle: MetaBundle
    injected: list[Injected]


def _grid(row: str, col: float) -> str:
    return f"{row}-{col:g}"


def fuzz_project(seed: int) -> FuzzProject:
    rng = random.Random(seed)
    n_levels = rng.randint(2, 4)
    names = sorted(rng.sample(LEVEL_POOL, n_levels + 1), key=LEVEL_POOL.index)
    elevations, z = {}, 0.0
    for name in names:
        elevations[name] = z
        z += rng.choice((2800.0, 3200.0, 3500.0, 4200.0))
    covered = names[:-1]  # the top level only closes the last storey
    rows = rng.sample(ROW_POOL, rng.randint(2, 5))
    cols = sorted(rng.sample(range(1, 21), rng.randint(3, 9)))
    cols_f = [c + (0.5 if rng.random() < 0.15 else 0.0) for c in cols]
    n_files = rng.randint(1, 3)
    files = [f"DA/Colonnes/PART{i + 1}.pdf" for i in range(n_files)]
    typical = {
        "count": rng.choice((4, 6, 8, 10)),
        "size": rng.choice(BAR_SIZES),
        "tie_size": rng.choice(("10M", "15M")),
        "spacing": rng.choice(SPACINGS_MM),
    }

    def build(source: str, level: str, row: str, col: float, **over) -> ElementExt:
        height = elevations[names[names.index(level) + 1]] - elevations[level]
        p = {**typical, **over}
        file = files[rows.index(row) % n_files] if source == "shop" else "plan.pdf"
        return make_element(
            source,
            level,
            row,
            col,
            count=p["count"],
            size=p["size"],
            tie_size=p["tie_size"],
            spacing_mm=p["spacing"],
            tie_count=round(height / p["spacing"]) if source == "shop" else None,
            fichier=file,
            feuillet=f"S-5{names.index(level):02d}" if source == "plan" else None,
            x=100.0 + 50 * col,
            y=100.0 + 40 * rows.index(row),
        )

    cells = [(lv, r, c) for lv in covered for r in rows for c in cols_f]
    plan = [build("plan", *cell) for cell in cells]
    shop = {cell: build("shop", *cell) for cell in cells}
    injected: list[Injected] = []
    for lv, r, c in rng.sample(cells, min(len(cells), rng.randint(3, 6))):
        kind = rng.choice(DEFECT_KINDS)
        if kind == "missing":
            del shop[(lv, r, c)]
        elif kind == "added":
            extra_col = max(cols_f) + 1
            shop[(lv, r, extra_col)] = build("shop", lv, r, extra_col)
            injected.append(Injected(kind, lv, _grid(r, extra_col)))
            continue
        else:
            if kind == "count":
                over = {"count": typical["count"] + rng.choice((-2, -1, 1, 2, 4))}
            elif kind == "size":
                over = {"size": rng.choice([s for s in BAR_SIZES if s != typical["size"]])}
            elif kind == "tie_size":
                over = {"tie_size": "15M" if typical["tie_size"] == "10M" else "10M"}
            else:
                over = {"spacing": rng.choice([s for s in SPACINGS_MM if s != typical["spacing"]])}
            shop[(lv, r, c)] = build("shop", lv, r, c, **over)
        injected.append(Injected(kind, lv, _grid(r, c)))
    bundle = MetaBundle(
        project=f"FUZZ{seed}",
        elements=plan + list(shop.values()),
        levels=[LevelInfo(level=n, name=n, elevation_mm=elevations[n]) for n in names],
    )
    return FuzzProject(bundle, injected)
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare/test_fuzz.py -v
```

Expected: 62 passed. A failure names the seed; reproduce with `fuzz_project(<seed>)` and fix the comparison, never the test.

- [ ] **Step 5: Commit and merge**

```bash
git add backend/l2c/mock/fuzz.py backend/tests/compare/test_fuzz.py
git commit -m "Add fuzz projects with injected defects"
```

```bash
git switch dev
git merge --no-ff ian/i7-fuzz
```


---

### Task I8: Outputs: per-shop JSON and PDF, by-plan-sheet report, XLSX, CLI

**Files:**
- Create: `backend/l2c/compare/outputs.py`, `backend/l2c/report/__init__.py` (empty), `backend/l2c/report/pdf.py`, `backend/l2c/report/xlsx.py`, `backend/l2c/compare/__main__.py`
- Test: `backend/tests/compare/test_outputs.py`

**Interfaces:**
- Consumes: `run_comparison` (I6), `read_bundle`, `write_models` (F2).
- Produces: `safe_name(fichier) -> str` (file-system safe, unique per path via a short hash, so two shop files with the same name in different folders never collide); `counts(findings) -> dict[status, int]`; `assign_to_shop_files(findings, bundle)` (every finding lands in exactly one shop file or in the `unassigned` list; a plan-only finding goes to the first shop file that covers its level); `comparison_files(findings, bundle) -> (list[ComparisonFile], unassigned)`; `by_plan_sheet(findings, bundle)`; `describe(element)`; `coverage_lines(bundle)` (each element type is stated as covered or `NOT COVERED` with the reason, in every report); `write_shop_report`, `write_plan_sheet_report`, `write_summary` (ReportLab, built-in fonts, footer `CONFIDENTIAL - hackathon use only`); `write_xlsx(path, findings, bundle)` (columns Feuillet, Localisation, Plan L2C, Dessin d'atelier, Statut, Confiance, Verification); CLI `python -m l2c.compare <metadata_dir> --out <dir> [--ml]` writing `findings.json`, `comparison/<name>.json` and `.pdf` for every shop file, `report/by_plan_sheet.pdf`, `report/summary.pdf`, `findings.xlsx`, printing counts only.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i8-outputs
```

Create `backend/tests/compare/test_outputs.py`:

```python
import json
import subprocess
import sys

import pymupdf
from openpyxl import load_workbook

from l2c.compare.outputs import (
    assign_to_shop_files,
    by_plan_sheet,
    comparison_files,
    counts,
    coverage_lines,
    safe_name,
)
from l2c.compare.run import run_comparison
from l2c.contract.io import write_bundle
from l2c.mock.generate import FILE_A, FILE_B, mock_project


def test_safe_name_is_filesystem_safe_and_unique_per_path():
    a = safe_name("DA/Colonnes/CLP COLONNES Partie 1.pdf")
    b = safe_name("DA/Dalles/CLP COLONNES Partie 1.pdf")
    assert a != b and "/" not in a and " " not in a and a.startswith("CLP_COLONNES_Partie_1-")


def test_every_finding_lands_in_exactly_one_shop_file_or_unassigned():
    m = mock_project()
    findings = run_comparison(m.bundle)
    by_file, unassigned = assign_to_shop_files(findings, m.bundle)
    assert set(by_file) == {FILE_A, FILE_B}
    placed = [f.id for fs in by_file.values() for f in fs] + [f.id for f in unassigned]
    assert len(placed) == len(set(placed))
    missing = next(f for f in findings if f.status == "missing")
    assert missing in by_file[FILE_A]  # N2 is covered by PART1 (sorted first); not unassigned


def test_plan_only_findings_with_no_covering_shop_file_are_unassigned():
    m = mock_project()
    findings = run_comparison(m.bundle)
    trimmed = [e for e in m.bundle.elements if not (e.source == "shop" and e.level == "N2")]
    m.bundle.elements = trimmed
    findings = run_comparison(m.bundle)
    _, unassigned = assign_to_shop_files(findings, m.bundle)
    assert any(f.level == "N2" for f in unassigned)


def test_comparison_files_counts_add_up():
    m = mock_project()
    findings = run_comparison(m.bundle)
    comps, unassigned = comparison_files(findings, m.bundle)
    total = sum(sum(c.counts.values()) for c in comps) + len(unassigned)
    plan_only_self = [
        f for f in findings if f.shop_ref is None and f.check_type != "cross.plan_vs_shop"
    ]
    assert total + len(plan_only_self) == len(findings)
    assert counts(findings)["non_compliant"] == 3


def test_by_plan_sheet_groups_by_title_block_sheet():
    m = mock_project()
    sections = by_plan_sheet(run_comparison(m.bundle), m.bundle)
    assert {"S-502", "S-503"} <= set(sections)


def test_coverage_lines_state_what_is_not_covered():
    lines = coverage_lines(mock_project().bundle)
    assert any(line.startswith("colonne: covered") for line in lines)
    assert any(line.startswith("dalle: NOT COVERED") for line in lines)


def test_cli_writes_all_outputs_and_counts_agree(tmp_path):
    meta, out = tmp_path / "meta", tmp_path / "out"
    write_bundle(meta, mock_project().bundle)
    r = subprocess.run(
        [sys.executable, "-m", "l2c.compare", str(meta), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("findings=") and "K-4" not in r.stdout
    names = {p.name for p in (out / "comparison").iterdir()}
    assert (
        sum(n.endswith(".json") for n in names) == 2 and sum(n.endswith(".pdf") for n in names) == 2
    )
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    per_shop = [
        json.loads(p.read_text(encoding="utf-8")) for p in (out / "comparison").glob("*.json")
    ]
    assert all("counts" in c and c["contract_version"] for c in per_shop)
    # xlsx rows == findings
    ws = load_workbook(out / "findings.xlsx").active
    assert ws.max_row == len(findings) + 1
    assert [c.value for c in ws[1]][:2] == ["Feuillet", "Localisation"]
    # PDF text contains the status counts and the coverage statement
    text = "".join(p.get_text() for p in pymupdf.open(out / "report" / "by_plan_sheet.pdf"))
    assert "Sheet S-502" in text and "NOT COVERED" in text and "CONFIDENTIAL" in text
    shop_pdf = next((out / "comparison").glob("*.pdf"))
    assert "Shop drawing comparison" in pymupdf.open(shop_pdf)[0].get_text()


def test_comparison_of_an_empty_project_still_writes_every_output(tmp_path):
    from l2c.contract.io import MetaBundle

    meta, out = tmp_path / "meta", tmp_path / "out"
    write_bundle(meta, MetaBundle(project="EMPTY"))
    r = subprocess.run(
        [sys.executable, "-m", "l2c.compare", str(meta), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert (out / "findings.json").read_text(encoding="utf-8").strip() == "[]"
    assert (out / "report" / "summary.pdf").is_file() and (out / "findings.xlsx").is_file()
    text = "".join(p.get_text() for p in pymupdf.open(out / "report" / "summary.pdf"))
    assert "NOT COVERED" in text  # coverage is stated even when nothing was found
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_outputs.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.compare.outputs'`.

- [ ] **Step 3: Write outputs, reports and the CLI**

Create empty `backend/l2c/report/__init__.py`, then:

Create `backend/l2c/compare/outputs.py`:

```python
"""Group findings into the files the engineer reads: per shop drawing, per plan sheet."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import PurePath

from l2c.compare.profile import profile
from l2c.contract import constants as C
from l2c.contract.io import MetaBundle
from l2c.contract.models import ComparisonFile, ElementExt, Finding

UNASSIGNED = "unassigned_missing"
NO_SHEET = "(no plan sheet)"


def safe_name(fichier: str) -> str:
    stem = PurePath(fichier).stem
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("_") or "file"
    digest = hashlib.sha1(fichier.encode("utf-8")).hexdigest()[:6]
    return f"{clean}-{digest}"


def counts(findings: list[Finding]) -> dict[str, int]:
    c = Counter(f.status for f in findings)
    return {s: c.get(s, 0) for s in C.STATUSES}


def _by_id(bundle: MetaBundle) -> dict[str, ElementExt]:
    return {e.id: e for e in bundle.elements}


def plan_sheet_of(f: Finding, by_id: dict[str, ElementExt]) -> str:
    if f.plan_ref and f.plan_ref.element_id in by_id:
        return by_id[f.plan_ref.element_id].feuillet or NO_SHEET
    return NO_SHEET


def assign_to_shop_files(
    findings: list[Finding], bundle: MetaBundle
) -> tuple[dict[str, list[Finding]], list[Finding]]:
    """Every shop file gets its findings; plan-only findings go to the file covering their level."""
    level_files: dict[str, list[str]] = defaultdict(list)
    for e in bundle.elements:
        if e.source == "shop" and e.fichier not in level_files[e.level]:
            level_files[e.level].append(e.fichier)
    for files in level_files.values():
        files.sort()
    by_file: dict[str, list[Finding]] = {s.fichier: [] for s in bundle.sheets if s.kind == "shop"}
    unassigned: list[Finding] = []
    for f in findings:
        if f.shop_ref:
            by_file.setdefault(f.shop_ref.fichier, []).append(f)
        elif f.plan_ref and f.check_type == "cross.plan_vs_shop":
            files = level_files.get(f.level)
            if files:
                by_file[files[0]].append(f)
            else:
                unassigned.append(f)
    return by_file, unassigned


def comparison_files(
    findings: list[Finding], bundle: MetaBundle
) -> tuple[list[ComparisonFile], list[Finding]]:
    by_id = _by_id(bundle)
    by_file, unassigned = assign_to_shop_files(findings, bundle)
    out: list[ComparisonFile] = []
    for fichier in sorted(by_file):
        fs = by_file[fichier]
        sheets = sorted({plan_sheet_of(f, by_id) for f in fs} - {NO_SHEET})
        out.append(
            ComparisonFile(
                contract_version=C.CONTRACT_VERSION,
                shop_file=fichier,
                revision=None,
                plan_sheets=sheets,
                counts=counts(fs),
                findings=fs,
            )
        )
    return out, unassigned


def by_plan_sheet(findings: list[Finding], bundle: MetaBundle) -> dict[str, list[Finding]]:
    by_id = _by_id(bundle)
    sections: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        sections[plan_sheet_of(f, by_id)].append(f)
    return dict(sorted(sections.items()))


def describe(e: ElementExt | None) -> str:
    if e is None:
        return ""
    p = profile(e)
    parts = []
    if p.count is not None and p.size:
        parts.append(f"{p.count}-{p.size}")
    if p.tie_size:
        spacing = f"@{p.spacing_mm:g}mm" if p.spacing_mm is not None else ""
        parts.append(f"{p.tie_size}{spacing}")
    return " ; ".join(parts)


def coverage_lines(bundle: MetaBundle) -> list[str]:
    """What the run covers, stated plainly in every report."""
    covered = Counter(e.type_element for e in bundle.elements)
    lines = []
    for t in C.ELEMENT_TYPES:
        plan_pages = sum(1 for s in bundle.sheets if s.kind == "plan" and s.type_element == t)
        shop_pages = sum(1 for s in bundle.sheets if s.kind == "shop" and s.type_element == t)
        if covered.get(t):
            lines.append(f"{t}: covered ({covered[t]} elements extracted)")
        elif plan_pages or shop_pages:
            lines.append(
                f"{t}: NOT COVERED ({plan_pages} plan pages, {shop_pages} shop pages present)"
            )
        else:
            lines.append(f"{t}: NOT COVERED (no sheets found)")
    return lines
```

Create `backend/l2c/report/pdf.py`:

```python
"""PDF reports with ReportLab (built-in fonts only, so it works the same on every OS)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from l2c.contract import constants as C
from l2c.contract.models import ComparisonFile, Finding

STYLES = getSampleStyleSheet()
CELL = ParagraphStyle("cell", parent=STYLES["BodyText"], fontSize=7.5, leading=9)
STATUS_COLORS = {
    C.STATUS_NON_COMPLIANT: colors.HexColor("#f8d7da"),
    C.STATUS_MISSING: colors.HexColor("#fde2c8"),
    C.STATUS_ADDED: colors.HexColor("#fff3cd"),
    C.STATUS_NEEDS_REVIEW: colors.HexColor("#e2e3f3"),
}
HEADER = ["Status", "Check", "Level", "Grid", "Plan vs shop", "Confidence", "Notes"]


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.drawString(0.5 * inch, 0.35 * inch, "CONFIDENTIAL - hackathon use only")
    canvas.drawRightString(landscape(letter)[0] - 0.5 * inch, 0.35 * inch, f"page {doc.page}")
    canvas.restoreState()


def _diff_text(f: Finding) -> str:
    if f.diffs:
        return "; ".join(f"{d.field}: plan {d.plan} / shop {d.shop}" for d in f.diffs)
    return f.evidence.rule.kind.replace("_", " ")


def _counts_table(counts: dict[str, int]) -> Table:
    data = [list(C.STATUSES), [str(counts.get(s, 0)) for s in C.STATUSES]]
    t = Table(data, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return t


def _findings_table(findings: list[Finding]) -> Table:
    rows = [HEADER]
    shades: list[tuple[int, colors.Color]] = []
    shown = [f for f in findings if f.status != C.STATUS_COMPLIANT]
    for i, f in enumerate(shown, start=1):
        rows.append(
            [
                f.status,
                f.check_type,
                f.level,
                f.grid or "-",
                Paragraph(_diff_text(f), CELL),
                f"{f.confidence:.2f}",
                Paragraph(f.notes or "", CELL),
            ]
        )
        if f.status in STATUS_COLORS:
            shades.append((i, STATUS_COLORS[f.status]))
    if len(rows) == 1:
        rows.append(["none", "", "", "", "no discrepancies to report", "", ""])
    t = Table(
        rows,
        repeatRows=1,
        colWidths=[
            0.9 * inch,
            1.3 * inch,
            0.5 * inch,
            0.6 * inch,
            3.4 * inch,
            0.7 * inch,
            2.4 * inch,
        ],
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#343a40")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    style += [("BACKGROUND", (0, i), (-1, i), c) for i, c in shades]
    t.setStyle(TableStyle(style))
    return t


def _doc(path: Path, title: str) -> SimpleDocTemplate:
    path.parent.mkdir(parents=True, exist_ok=True)
    return SimpleDocTemplate(
        str(path),
        pagesize=landscape(letter),
        title=title,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.6 * inch,
    )


def write_shop_report(path: Path, comp: ComparisonFile, coverage: list[str]) -> None:
    story = [
        Paragraph(f"Shop drawing comparison: {comp.shop_file}", STYLES["Title"]),
        Paragraph(
            f"Plan sheets compared: {', '.join(comp.plan_sheets) or 'none'}", STYLES["Normal"]
        ),
        Spacer(1, 8),
        _counts_table(comp.counts),
        Spacer(1, 10),
        Paragraph("Discrepancies and items to review", STYLES["Heading2"]),
        _findings_table(comp.findings),
        Spacer(1, 10),
        Paragraph("Coverage", STYLES["Heading2"]),
        *[Paragraph(line, STYLES["Normal"]) for line in coverage],
    ]
    _doc(path, f"Comparison {comp.shop_file}").build(
        story, onFirstPage=_footer, onLaterPages=_footer
    )


def write_plan_sheet_report(
    path: Path, sections: dict[str, list[Finding]], coverage: list[str], unassigned: list[Finding]
) -> None:
    from l2c.compare.outputs import counts

    story = [Paragraph("Report by plan sheet", STYLES["Title"])]
    for sheet, fs in sections.items():
        story += [
            Paragraph(f"Sheet {sheet}", STYLES["Heading2"]),
            _counts_table(counts(fs)),
            Spacer(1, 6),
            _findings_table(fs),
            Spacer(1, 12),
        ]
    if unassigned:
        story += [
            Paragraph(
                "Plan elements not covered by any shop file (unassigned)", STYLES["Heading2"]
            ),
            _findings_table(unassigned),
            Spacer(1, 12),
        ]
    story += [
        Paragraph("Coverage", STYLES["Heading2"]),
        *[Paragraph(line, STYLES["Normal"]) for line in coverage],
    ]
    _doc(path, "Report by plan sheet").build(story, onFirstPage=_footer, onLaterPages=_footer)


def write_summary(path: Path, project: str, findings: list[Finding], coverage: list[str]) -> None:
    from l2c.compare.outputs import counts

    story = [
        Paragraph(f"L2C summary: {project}", STYLES["Title"]),
        _counts_table(counts(findings)),
        Spacer(1, 10),
        Paragraph("Coverage", STYLES["Heading2"]),
        *[Paragraph(line, STYLES["Normal"]) for line in coverage],
    ]
    _doc(path, f"Summary {project}").build(story, onFirstPage=_footer, onLaterPages=_footer)
```

Create `backend/l2c/report/xlsx.py`:

```python
"""Jury-style list: sheet, location, plan value, shop value, status."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from l2c.compare.outputs import NO_SHEET, describe, plan_sheet_of
from l2c.contract.io import MetaBundle
from l2c.contract.models import Finding

HEADER = [
    "Feuillet",
    "Localisation",
    "Plan L2C",
    "Dessin d'atelier",
    "Statut",
    "Confiance",
    "Verification",
]


def write_xlsx(path: Path, findings: list[Finding], bundle: MetaBundle) -> None:
    by_id = {e.id: e for e in bundle.elements}
    wb = Workbook()
    ws = wb.active
    ws.title = "findings"
    ws.append(HEADER)
    for f in findings:
        plan = by_id.get(f.plan_ref.element_id) if f.plan_ref and f.plan_ref.element_id else None
        shop = by_id.get(f.shop_ref.element_id) if f.shop_ref and f.shop_ref.element_id else None
        sheet = plan_sheet_of(f, by_id)
        ws.append(
            [
                sheet if sheet != NO_SHEET else (shop.fichier if shop else ""),
                f"{f.level} {f.grid or ''}".strip(),
                describe(plan),
                describe(shop),
                f.status,
                f.confidence,
                f.check_type,
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
```

Create `backend/l2c/compare/__main__.py`:

```python
"""`python -m l2c.compare <metadata_dir> --out <dir>`: findings, per-shop files, reports, XLSX."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from l2c.compare.outputs import by_plan_sheet, comparison_files, counts, coverage_lines, safe_name
from l2c.compare.run import run_comparison
from l2c.contract.io import read_bundle, write_models
from l2c.report.pdf import write_plan_sheet_report, write_shop_report, write_summary
from l2c.report.xlsx import write_xlsx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l2c.compare")
    ap.add_argument("metadata_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--ml", action="store_true", help="learn pair probabilities from the project's own pairs"
    )
    args = ap.parse_args(argv)
    if not (args.metadata_dir / "manifest.json").is_file():
        print(f"no manifest.json in {args.metadata_dir}", file=sys.stderr)
        return 2
    bundle = read_bundle(args.metadata_dir)
    findings = run_comparison(bundle, use_ml=args.ml)
    out = args.out
    coverage = coverage_lines(bundle)
    write_models(out / "findings.json", findings)
    comps, unassigned = comparison_files(findings, bundle)
    for comp in comps:
        name = safe_name(comp.shop_file)
        write_models(out / "comparison" / f"{name}.json", comp)
        write_shop_report(out / "comparison" / f"{name}.pdf", comp, coverage)
    write_plan_sheet_report(
        out / "report" / "by_plan_sheet.pdf", by_plan_sheet(findings, bundle), coverage, unassigned
    )
    write_summary(out / "report" / "summary.pdf", bundle.project, findings, coverage)
    write_xlsx(out / "findings.xlsx", findings, bundle)
    print(f"findings={len(findings)} shop_files={len(comps)} statuses={counts(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare/test_outputs.py -v
python scripts/check.py
```

Expected: 8 passed (safe names, every finding placed once, unassigned plan-only findings, counts add up, grouping by plan sheet, coverage statements, the full CLI run producing every file with matching counts, and an empty project still producing every output with a coverage statement).

- [ ] **Step 5: Try the CLI on the committed fixtures**

```powershell
python -m l2c.compare shared/fixtures/mock_a/metadata --out data/out/mock
```

Expected: `findings=... shop_files=2 statuses={{...}}`. Open `data/out/mock/report/by_plan_sheet.pdf` and one file under `data/out/mock/comparison/` and check they read well (counts first, discrepancy table, coverage). `data/` is git-ignored.

- [ ] **Step 6: Commit and merge**

```bash
git add backend/l2c/compare backend/l2c/report backend/tests/compare/test_outputs.py
git commit -m "Add comparison outputs, reports and CLI"
```

```bash
git switch dev
git merge --no-ff ian/i8-outputs
```


---

### Task I9 (second tier): Learned pair probabilities, trained on the project itself

Start after the core gate (I1 to I8 pass and Eric's real CLP bundle has run through the comparison, Task I10).

**Files:**
- Create: `backend/l2c/compare/ml/__init__.py` (empty), `features.py`, `dataset.py`, `pair_model.py`, `evaluate.py`; `scripts/train_pair_model.py`
- Test: `backend/tests/compare/test_ml.py`

**Interfaces:**
- Consumes: `run_comparison`/`add_pair_probabilities` (I6), `compare_pair` (I3), `match` (I1).
- Produces: `features(finding) -> list[float]` (13 features, names in `FEATURE_NAMES`: the diffs, both extraction qualities, match method and margin, weak flags); `build_dataset(seeds)` (synthetic projects) and `build_dataset_from_bundle(bundle, seed=0, variants_per_pair=3)` (mutates the project's own agreeing pairs: a genuine injected defect is label 1; an extraction-noise difference carrying quality and flags sampled from the project's own weak elements is label 0); `PairModel` (gradient boosting plus isotonic calibration, fixed seed, hash-checked save/load); `rule_scores`, `model_scores`, `keep_model(rule, model)` (kill criterion: keep only if recall is at least the rule's and false alarms are fewer); `run_comparison(bundle, use_ml=True)` trains on the project's own pairs when it has at least 50 agreeing pairs and attaches `evidence.ml.pair_probability`.
- Invariant (tested): ML never lowers a `non_compliant` / `missing` / `added` verdict; it can only raise a no-difference pair to `needs_review` and re-rank by probability.

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i9-ml
```

Create `backend/tests/compare/test_ml.py`:

```python
import pytest

from l2c.compare.ml.dataset import build_dataset, build_dataset_from_bundle
from l2c.compare.ml.evaluate import keep_model, model_scores, rule_scores
from l2c.compare.ml.features import FEATURE_NAMES, features
from l2c.compare.ml.pair_model import MODEL_VERSION, load, save, train
from l2c.compare.run import MIN_PAIRS_TO_LEARN, run_comparison
from l2c.mock.fuzz import fuzz_project
from l2c.mock.generate import mock_project


def big_project():
    for seed in range(200):
        fp = fuzz_project(seed)
        if sum(e.source == "plan" for e in fp.bundle.elements) >= 2 * MIN_PAIRS_TO_LEARN:
            return fp
    raise AssertionError("no large fuzz project")


def test_features_have_the_documented_names_and_length():
    f = next(
        x for x in run_comparison(mock_project().bundle) if x.check_type == "cross.plan_vs_shop"
    )
    assert len(features(f)) == len(FEATURE_NAMES)


def test_dataset_from_synthetic_projects_has_both_classes():
    X, y = build_dataset(range(5))
    assert len(X) == len(y) and 0 < sum(y) < len(y)


def test_dataset_from_a_bundle_has_clean_real_and_noise_rows():
    fp = big_project()
    X, y = build_dataset_from_bundle(fp.bundle)
    assert len(X) > 100 and 0 < sum(y) < len(y)


def test_model_round_trip_checks_the_hash(tmp_path):
    fp = big_project()
    X, y = build_dataset_from_bundle(fp.bundle)
    model = train(X, y)
    digest = save(model, tmp_path / "m.pkl")
    again = load(tmp_path / "m.pkl", digest)
    assert again.version == MODEL_VERSION
    assert list(again.predict_many(X[:5])) == list(model.predict_many(X[:5]))
    with pytest.raises(ValueError):
        load(tmp_path / "m.pkl", "0" * 64)


def test_training_is_deterministic():
    fp = big_project()
    X, y = build_dataset_from_bundle(fp.bundle)
    a, b = train(X, y).predict_many(X[:20]), train(X, y).predict_many(X[:20])
    assert list(a) == list(b)


def test_rule_baseline_and_keep_criterion():
    X, y = build_dataset(range(8))
    rule = rule_scores(X, y)
    assert 0.0 <= rule.precision <= 1.0
    never_better = model_scores(train(X, y).predict_many(X), X, y)
    assert isinstance(keep_model(rule, never_better), bool)


def test_ml_never_lowers_a_deterministic_verdict():
    fp = big_project()
    base = {(f.check_type, f.id): f for f in run_comparison(fp.bundle)}
    with_ml = {(f.check_type, f.id): f for f in run_comparison(fp.bundle, use_ml=True)}
    assert base.keys() == with_ml.keys()
    firm = {"non_compliant", "missing", "added"}
    for key, f in base.items():
        if f.status in firm:
            assert with_ml[key].status == f.status
    pairs = [
        f
        for f in with_ml.values()
        if f.check_type == "cross.plan_vs_shop" and f.shop_ref and f.plan_ref
    ]
    assert pairs and all(
        f.evidence.ml and f.evidence.ml.pair_probability is not None for f in pairs
    )


def test_small_projects_skip_the_model():
    bundle = mock_project().bundle  # fewer than MIN_PAIRS_TO_LEARN agreeing pairs
    plain = run_comparison(bundle)
    assert [f.model_dump_json() for f in run_comparison(bundle, use_ml=True)] == [
        f.model_dump_json() for f in plain
    ]
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_ml.py -v
```

Expected: `ModuleNotFoundError: No module named 'l2c.compare.ml'`.

- [ ] **Step 3: Write the ML modules and the training script**

Create empty `backend/l2c/compare/ml/__init__.py`, then:

Create `backend/l2c/compare/ml/features.py`:

```python
"""Features for the pair-discrepancy model. Everything comes from the deterministic comparison:
the diffs, how trustworthy both extractions are, and how the pair was matched."""

from __future__ import annotations

from l2c.contract.models import Finding

FEATURE_NAMES = (
    "rule_fired",
    "n_diffs",
    "count_rel_change",
    "size_changed",
    "tie_size_changed",
    "spacing_rel_change",
    "plan_overall",
    "shop_overall",
    "min_overall",
    "match_near",
    "match_margin",
    "n_flags",
    "weak_flag",
)
WEAK_FLAGS = {"weak_strip_assignment", "weak_binding", "second_pass_binding", "ambiguous_cell"}


def _rel(plan: float | None, shop: float | None) -> float:
    if plan in (None, 0) or shop is None:
        return 0.0
    return abs(float(shop) - float(plan)) / abs(float(plan))


def features(f: Finding) -> list[float]:
    by_field = {d.field: d for d in f.diffs}
    ev = f.evidence
    po = ev.extraction.plan_overall
    so = ev.extraction.shop_overall
    present = [v for v in (po, so) if v is not None]
    m = ev.match
    return [
        1.0 if ev.rule.fired else 0.0,
        float(len(f.diffs)),
        _rel(by_field["count"].plan, by_field["count"].shop) if "count" in by_field else 0.0,
        1.0 if "size" in by_field else 0.0,
        1.0 if "tie_size" in by_field else 0.0,
        _rel(by_field["spacing_mm"].plan, by_field["spacing_mm"].shop)
        if "spacing_mm" in by_field
        else 0.0,
        1.0 if po is None else po,
        1.0 if so is None else so,
        min(present) if present else 1.0,
        1.0 if (m and m.method == "near_col") else 0.0,
        1.0 if (m is None or m.margin_to_runner_up is None) else m.margin_to_runner_up,
        float(len(ev.extraction.flags)),
        1.0 if WEAK_FLAGS & set(ev.extraction.flags) else 0.0,
    ]
```

Create `backend/l2c/compare/ml/dataset.py`:

```python
"""Training data for the pair model, made from synthetic projects with known ground truth.

Labels: 1 = a real discrepancy was injected in the drawings; 0 = no real discrepancy.
Noise rows teach the model that a difference seen through an unreliable extraction is often not
real: an untouched pair whose shop side is corrupted AND flagged as weak is labelled 0.
"""

from __future__ import annotations

import copy
import random

from l2c.compare.cross import compare_pair
from l2c.compare.ml.features import features
from l2c.contract.models import ElementExt, Finding
from l2c.match.matcher import Pair, match
from l2c.mock.fuzz import fuzz_project


def _pair_findings(elements: list[ElementExt]) -> dict[tuple[str, str | None], Finding]:
    plan = [e for e in elements if e.source == "plan"]
    shop = [e for e in elements if e.source == "shop"]
    plan_levels = {e.level for e in plan}
    shop_levels = {e.level for e in shop}
    out: dict[tuple[str, str | None], Finding] = {}
    for p in match(plan, shop):
        f = compare_pair(p, plan_levels, shop_levels)
        out[(f.level, f.grid)] = f
    return out


def _corrupt(e: ElementExt, rng: random.Random) -> ElementExt:
    """Simulate extraction noise on a shop element: a wrong digit and weak provenance."""
    e = copy.deepcopy(e)
    vert = e.armature[0]
    if vert.quantite is not None:
        vert.quantite = max(1, vert.quantite + rng.choice((-2, -1, 1, 2)))
    e.quality = e.quality.model_copy(
        update={
            "overall": round(rng.uniform(0.2, 0.65), 3),
            "flags": ["weak_strip_assignment"],
        }
    )
    return e


def build_dataset(seeds: range, noise_per_project: int = 6) -> tuple[list[list[float]], list[int]]:
    X: list[list[float]] = []
    y: list[int] = []
    for seed in seeds:
        fp = fuzz_project(seed)
        truth = {(i.level, i.grid) for i in fp.injected}
        findings = _pair_findings(fp.bundle.elements)
        for key, f in findings.items():
            X.append(features(f))
            y.append(1 if key in truth else 0)
        rng = random.Random(seed * 7919 + 1)
        clean = [(k, f) for k, f in findings.items() if k not in truth and f.status == "compliant"]
        for key, _f in rng.sample(clean, min(noise_per_project, len(clean))):
            shop_el = next(
                e for e in fp.bundle.elements if e.source == "shop" and (e.level, e.grid) == key
            )
            noisy = [_corrupt(e, rng) if e.id == shop_el.id else e for e in fp.bundle.elements]
            nf = _pair_findings(noisy)[key]
            X.append(features(nf))
            y.append(0)
    return X, y


def build_dataset_from_bundle(
    bundle, seed: int = 0, variants_per_pair: int = 3
) -> tuple[list[list[float]], list[int]]:
    """Training rows from a *real* extraction: mutate matched pairs, reuse the real noise.

    For every matched pair three kinds of rows are made, all with the shop element's real quality
    fields and flags: clean (label 0), a genuine injected defect (label 1), and an extraction-noise
    difference (label 0) whose quality/flags are drawn from the weak elements of the same project.
    """
    rng = random.Random(seed)
    plan = [e for e in bundle.elements if e.source == "plan"]
    shop = [e for e in bundle.elements if e.source == "shop"]
    weak = [e for e in shop if e.quality.flags or e.quality.overall < 0.8] or shop
    plan_levels = {e.level for e in plan}
    shop_levels = {e.level for e in shop}
    X: list[list[float]] = []
    y: list[int] = []
    for pair in match(plan, shop):
        if pair.plan is None or pair.shop is None or pair.method == "unbound":
            continue
        f0 = compare_pair(pair, plan_levels, shop_levels)
        if f0.evidence.rule.fired:
            continue  # only start from pairs that really agree
        X.append(features(f0))
        y.append(0)
        for _ in range(variants_per_pair):
            changed = copy.deepcopy(pair.shop)
            vert = changed.armature[0]
            if vert.quantite is None:
                break
            vert.quantite = max(1, vert.quantite + rng.choice((-3, -2, -1, 1, 2, 3)))
            real = Pair(pair.plan, changed, pair.method, pair.cost, pair.margin)
            X.append(features(compare_pair(real, plan_levels, shop_levels)))
            y.append(1)
            donor = rng.choice(weak)
            noisy = copy.deepcopy(changed)
            noisy.quality = noisy.quality.model_copy(
                update={"overall": donor.quality.overall, "flags": list(donor.quality.flags)}
            )
            X.append(
                features(
                    compare_pair(
                        Pair(
                            pair.plan,
                            noisy,
                            pair.method,
                            donor.quality.location.margin_to_runner_up,
                            donor.quality.location.margin_to_runner_up,
                        ),
                        plan_levels,
                        shop_levels,
                    )
                )
            )
            y.append(0)
    return X, y
```

Create `backend/l2c/compare/ml/pair_model.py`:

```python
"""Pair-discrepancy model: probability that a matched pair is a real non-conformity.

Gradient boosting + isotonic calibration (scikit-learn, CPU, deterministic with a fixed seed).
It can only raise a verdict to needs_review; it never clears a deterministic diff (fusion.py).
"""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier

from l2c.compare.ml.features import FEATURE_NAMES, features
from l2c.contract.models import Finding

MODEL_VERSION = "pair-hgb-iso-v1"


@dataclass
class PairModel:
    clf: CalibratedClassifierCV
    version: str = MODEL_VERSION

    def predict(self, f: Finding) -> float:
        return float(self.clf.predict_proba(np.array([features(f)]))[0, 1])

    def predict_many(self, X: list[list[float]]) -> np.ndarray:
        return self.clf.predict_proba(np.array(X))[:, 1]


def train(X: list[list[float]], y: list[int], seed: int = 0) -> PairModel:
    assert len(FEATURE_NAMES) == len(X[0])
    base = HistGradientBoostingClassifier(max_iter=120, learning_rate=0.08, random_state=seed)
    clf = CalibratedClassifierCV(base, method="isotonic", cv=3)
    clf.fit(np.array(X), np.array(y))
    return PairModel(clf)


def save(model: PairModel, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = pickle.dumps(model)
    path.write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()


def load(path: Path, expected_sha256: str | None = None) -> PairModel:
    blob = path.read_bytes()
    if expected_sha256 and hashlib.sha256(blob).hexdigest() != expected_sha256:
        raise ValueError(f"{path} does not match the recorded SHA-256")
    return pickle.loads(blob)  # noqa: S301  (our own file, hash-checked)
```

Create `backend/l2c/compare/ml/evaluate.py`:

```python
"""Held-out evaluation: pair model versus the deterministic rule at the same operating point.

Kill criterion (spec 10.22): keep the model only if, at recall >= the rule's recall, it makes
fewer false alarms than the rule; otherwise keep the rule.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from l2c.compare.ml.features import FEATURE_NAMES
from l2c.contract import constants as C

RULE_FIRED = FEATURE_NAMES.index("rule_fired")
MIN_OVERALL = FEATURE_NAMES.index("min_overall")


@dataclass(frozen=True)
class Scores:
    precision: float
    recall: float
    false_alarms: int
    ece: float | None = None


def _pr(pred: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    return tp / max(tp + fp, 1), tp / max(tp + fn, 1), fp


def expected_calibration_error(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (p >= lo) & ((p < hi) | (hi == 1.0))
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(ece)


def rule_scores(X: list[list[float]], y: list[int]) -> Scores:
    a = np.array(X)
    pred = ((a[:, RULE_FIRED] == 1) & (a[:, MIN_OVERALL] >= C.TRUST_MIN_FOR_VERDICT)).astype(int)
    p, r, fp = _pr(pred, np.array(y))
    return Scores(p, r, fp)


def model_scores(probs: np.ndarray, X: list[list[float]], y: list[int]) -> Scores:
    """Flag a pair when the rule fired and the model says it is probably real."""
    a = np.array(X)
    truth = np.array(y)
    best = Scores(0.0, 0.0, 10**9)
    target_recall = rule_scores(X, y).recall
    for t in np.linspace(0.05, 0.95, 19):
        pred = ((a[:, RULE_FIRED] == 1) & (probs >= t)).astype(int)
        p, r, fp = _pr(pred, truth)
        if r >= target_recall - 1e-9 and fp < best.false_alarms:
            best = Scores(p, r, fp, expected_calibration_error(probs, truth))
    return best


def keep_model(rule: Scores, model: Scores) -> bool:
    return model.recall >= rule.recall - 1e-9 and model.false_alarms < rule.false_alarms
```

Create `scripts/train_pair_model.py`:

```python
"""Train and evaluate the pair model on synthetic projects; prints aggregates only.

Usage: python scripts/train_pair_model.py [--out models/pair_model.pkl]
The model file is git-ignored; its SHA-256 is printed so a run can record it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from l2c.compare.ml import pair_model
from l2c.compare.ml.dataset import build_dataset
from l2c.compare.ml.evaluate import keep_model, model_scores, rule_scores


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("models/pair_model.pkl"))
    ap.add_argument("--train-seeds", type=int, default=120)
    ap.add_argument("--test-seeds", type=int, default=60)
    args = ap.parse_args()
    Xtr, ytr = build_dataset(range(args.train_seeds))
    Xte, yte = build_dataset(range(10_000, 10_000 + args.test_seeds))
    model = pair_model.train(Xtr, ytr)
    rule = rule_scores(Xte, yte)
    ml = model_scores(model.predict_many(Xte), Xte, yte)
    print(f"train rows={len(Xtr)} positives={sum(ytr)}   test rows={len(Xte)} positives={sum(yte)}")
    print(
        f"rule : precision={rule.precision:.3f} recall={rule.recall:.3f} "
        f"false_alarms={rule.false_alarms}"
    )
    print(
        f"model: precision={ml.precision:.3f} recall={ml.recall:.3f} "
        f"false_alarms={ml.false_alarms} ece={ml.ece:.3f}"
    )
    verdict = "KEEP the model" if keep_model(rule, ml) else "DROP the model (rule is as good)"
    print("decision:", verdict)
    print("sha256:", pair_model.save(model, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

```powershell
python -m pytest backend/tests/compare/test_ml.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Evaluate honestly and record the decision**

```powershell
python scripts/train_pair_model.py --out models/pair_model.pkl
```

Expected on the purely synthetic benchmark: the deterministic rule is already perfect (precision 1.000, recall 1.000, 0 false alarms), so the decision line says `DROP the model (rule is as good)`. That is the kill criterion working: do not claim ML value from a benchmark where the rule already wins.

The meaningful test uses real pairs (needs Eric's bundle, Task I10): in a measured run on CLP, with the model trained on levels N2, N4, RDC and tested on N3, N5, SS using `build_dataset_from_bundle`, the rule reached precision 0.50 and recall 0.20 (because most real pairs fall below the 0.7 trust bar), while the model reached precision 0.96 and recall 1.00, ECE 0.018 (decision KEEP). Caveat to state in the pitch: the noise rows are sampled from the project's own weak elements, so this shows the model learns the project's noise pattern, not that it finds defects the rule cannot see. Report both numbers in the ablation table: deterministic only, plus the model.

- [ ] **Step 6: Commit and merge**

```bash
git add backend/l2c/compare/ml scripts/train_pair_model.py backend/tests/compare/test_ml.py
git commit -m "Add per-project learned pair probabilities"
```

```bash
git switch dev
git merge --no-ff ian/i9-ml
```


---

### Task I10: Integration with Eric's real extraction (core gate)

**Files:**
- Create: `scripts/findings_summary.py`
- Test: `backend/tests/compare/test_findings_summary.py`

**Interfaces:**
- Produces: `summarise(findings: list[dict]) -> str`, `show_cell(findings, grid, level) -> str` (prints plan and shop values for one cell; local use).

- [ ] **Step 1: Branch and write the failing test**

```bash
git switch dev
git pull
git switch -c ian/i10-integration
```

Create `backend/tests/compare/test_findings_summary.py`:

```python
import importlib.util
from pathlib import Path

from l2c.compare.run import run_comparison
from l2c.mock.generate import mock_project

spec = importlib.util.spec_from_file_location(
    "findings_summary", Path(__file__).resolve().parents[3] / "scripts" / "findings_summary.py"
)
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)


def dumped():
    return [f.model_dump(mode="json") for f in run_comparison(mock_project().bundle)]


def test_summary_counts_every_finding():
    text = fs.summarise(dumped())
    assert "findings" in text and "non_compliant" in text and "cross.plan_vs_shop" in text


def test_show_cell_prints_plan_and_shop_values():
    text = fs.show_cell(dumped(), "K-4", "N2")
    assert "count: plan 4 / shop 6" in text and "non_compliant" in text
    assert fs.show_cell(dumped(), "Z-99", None) == "no finding for that cell"
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/compare/test_findings_summary.py -v
```

Expected: `FileNotFoundError` for `scripts/findings_summary.py`.

- [ ] **Step 3: Write the script**

Create `scripts/findings_summary.py`:

```python
"""Summarise a findings.json (local use; may print values when you ask for one cell).

Usage:
  python scripts/findings_summary.py data/out/CLP/findings.json
  python scripts/findings_summary.py data/out/CLP/findings.json --grid K-6 --level N2
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
```

- [ ] **Step 4: Run the test**

```powershell
python -m pytest backend/tests/compare/test_findings_summary.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Receive Eric's real metadata (never through git or any cloud)**

Eric sends the folder `data/out/CLP/metadata` (seven JSON files) by AirDrop or USB drive. Ian places it at `data/out/CLP/metadata`. Both `data/` folders are git-ignored; the hook refuses anything there.

- [ ] **Step 6: Run the comparison on real data**

```powershell
python -m l2c.compare data/out/CLP/metadata --out data/out/CLP
python scripts/findings_summary.py data/out/CLP/findings.json
```

Baseline measured on the real CLP bundle (columns only; 394 plan and 858 shop elements): `findings=541 shop_files=12`, statuses `compliant 82, non_compliant 8, missing 4, added 22, needs_review 425`; by check: `cross.plan_vs_shop` 453, `self.peer_outlier` 83, `cross.shop_vs_shop` 4, `self.internal_consistency` 1. The same numbers come out with `--ml` (verdicts are never lowered). Whole run takes seconds.

- [ ] **Step 7: Check the two known cases**

```powershell
python scripts/findings_summary.py data/out/CLP/findings.json --grid K-6 --level N2
python scripts/findings_summary.py data/out/CLP/findings.json --grid I-13 --level N4
```

Expected:

- `K-6` at `N2`: `cross.plan_vs_shop`, `needs_review`, trust 0.60, `size: plan 35M / shop 25M` and a `self.peer_outlier` row for the same cell. The difference is found; it is not a firm `non_compliant` because the plan block's binding confidence is 0.60, below the 0.7 verdict bar (Eric's Task E13 calibration addresses this).
- `I-13` at `N4`: `cross.plan_vs_shop`, `non_compliant`, trust 0.82, `spacing_mm: plan 304.8 / shop 152.4` (12 inch against 6 inch ties) and a `self.peer_outlier` row.

- [ ] **Step 8: Read the reports like an engineer**

Open `data/out/CLP/report/by_plan_sheet.pdf` and two files under `data/out/CLP/comparison/`. Check: per-sheet counts add up to the findings; each discrepancy row names level, grid cell, plan and shop values and a confidence; the coverage section says beams, slabs, foundations and walls are `NOT COVERED`; every shop file has its own JSON and PDF.

- [ ] **Step 9: Time it and record the numbers**

Note the seconds for extract and compare, the counts above, and any difference from the baseline in the team's sync notes. A difference means a contract or data assumption changed; find which before moving on.

- [ ] **Step 10: Commit and merge**

```bash
git add scripts/findings_summary.py backend/tests/compare/test_findings_summary.py
git commit -m "Add findings summary tool"
```

```bash
git switch dev
git merge --no-ff ian/i10-integration
```

