"""A synthetic project and the pipeline's outputs on it, to show the deliverables' format in git.

python scripts/make_mock_outputs.py

The real projects' outputs hold drawing data and stay out of git (deliverables/). This writes a
small made-up project (one plan sheet, three shop drawings, invented values, two planted
differences) and runs the same pipeline on it, into shared/fixtures/mock_outputs/:

- project/            the generated input PDFs (plans at the top, shop drawings under DA/)
- elements/           one free-form element JSON per PDF
- findings.json, assignment.json, progress.json
- findings.pdf        the report
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
OUT = REPO / "shared" / "fixtures" / "mock_outputs"

GENERAL = "NOTES GENERALES: BETON 30 MPA, ACIER 400W, RECOUVREMENT SELON DEVIS, ENROBAGE 40 MM."


def _sheet(path: Path, sheet: str, title: str, notes: list[tuple[float, float, list[str]]]) -> None:
    """One 36 x 24 in sheet: a 4 x 4 grid (rows A-D, columns 1-4), notes at grid positions and a
    title block."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=2592, height=1728)
    x0, y0, step = 300.0, 250.0, 400.0
    for i in range(4):  # gridlines and their labels
        x = x0 + i * step
        page.draw_line((x, y0 - 60), (x, y0 + 3 * step + 60), color=(0.6, 0.6, 0.6), width=0.5)
        page.insert_text((x - 6, y0 - 80), str(i + 1), fontsize=24)
        y = y0 + i * step
        page.draw_line((x0 - 60, y), (x0 + 3 * step + 60, y), color=(0.6, 0.6, 0.6), width=0.5)
        page.insert_text((x0 - 120, y + 8), "ABCD"[i], fontsize=24)
    for row, col, lines in notes:  # a note beside the member at (row, col)
        x, y = x0 + (col - 1) * step + 30, y0 + row * step + 40
        page.draw_rect(pymupdf.Rect(x - 40, y - 60, x - 10, y - 30), color=(0, 0, 0), width=1)
        for k, text in enumerate(lines):
            page.insert_text((x, y + 16 * k), text, fontsize=11)
    page.insert_text((300, 1600), GENERAL, fontsize=12)
    page.insert_text((2100, 1600), title, fontsize=16)
    page.insert_text((2100, 1640), f"FEUILLET {sheet}", fontsize=16)
    page.insert_text((2400, 1680), sheet, fontsize=28)
    doc.save(path)
    doc.close()


def make_project(root: Path) -> Path:
    project = root / "MOCK"
    # plan, level 2: columns at B-2 and C-3, a slab note at B-3
    _sheet(
        project / "MOCK_PLAN_STR.pdf",
        "S-201",
        "PLAN DE STRUCTURE NIVEAU 2",
        [
            (1, 2, ["COLONNE B-2", "ARM.: 4-25M", 'LIG.: 10M@12" c/c']),
            (2, 3, ["COLONNE C-3", "ARM.: 6-20M", 'LIG.: 10M@10" c/c']),
            (1, 3, ["DALLE", "15M@300 c/c"]),
        ],
    )
    # shop drawings: the B-2 column agrees; C-3 has 4 bars instead of 6; the slab spacing differs
    _sheet(
        project / "DA" / "Colonnes" / "MOCK_COLONNES NIV 2.pdf",
        "A-101",
        "COLONNES NIV-2@3",
        [
            (1, 2, ["COLONNE B-2", "VERT: 4 25M 25Z9-06", 'ETRI: 22 10M 10ET13X21 @12"']),
            (2, 3, ["COLONNE C-3", "VERT: 4 20M 20Z9-06", 'ETRI: 26 10M 10ET13X21 @10"']),
        ],
    )
    _sheet(
        project / "DA" / "Dalles" / "MOCK_DALLE NIV 2.pdf",
        "A-201",
        "DALLE NIVEAU 2",
        [(1, 3, ["DALLE", "15M@350"])],
    )
    _sheet(
        project / "DA" / "Poutres" / "MOCK_POUTRES NIV 2.pdf",
        "A-301",
        "POUTRES NIVEAU 2",
        [(3, 1, ["POUTRE P-1", "4 20M 20-06"])],
    )
    return project


def main() -> int:
    from l2c.pipeline.stream import run

    with tempfile.TemporaryDirectory() as tmp:
        project = make_project(Path(tmp))
        out = Path(tmp) / "out"
        run(project, out, llm="none", ocr_cache=None, file_cache=None, partial_every=1e9)
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)
        shutil.copytree(project, OUT / "project")
        shutil.copytree(out / "elements", OUT / "elements")
        for name in ("findings.json", "findings.pdf", "assignment.json", "progress.json"):
            shutil.copy2(out / name, OUT / name)
    print(f"written to {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
