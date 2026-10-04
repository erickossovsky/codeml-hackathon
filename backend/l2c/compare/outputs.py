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
