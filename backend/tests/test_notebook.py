"""The demonstration notebook runs end to end, on a small generated project (no real drawings)."""

from pathlib import Path

import pymupdf
import pytest

nbformat = pytest.importorskip("nbformat")
nbclient = pytest.importorskip("nbclient")

REPO = Path(__file__).resolve().parents[2]
WORDS = "NOTE GENERALE BETON ARME ACIER 400W RECOUVREMENT SELON DEVIS ET PLANS STRUCTURE"


def _pdf(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    for i, text in enumerate(lines):
        page.insert_text((40, 40 + 18 * i), text, fontsize=10)
    doc.save(path)
    doc.close()


def test_demo_notebook_runs_on_a_small_project(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _pdf(project / "PLAN_S.pdf", ["COLONNE B-3", "ARM.: 4-20M", 'LIG.: 10M@8"', WORDS, WORDS])
    _pdf(
        project / "DA" / "Colonnes" / "C1.pdf",
        ["COLONNE B-3", "VERT: 6 20M 20Z3150", 'ETRI: 9 10M @8"', WORDS, WORDS],
    )
    monkeypatch.setenv("L2C_PROJECT", str(project))
    monkeypatch.setenv("L2C_OUT", str(tmp_path / "out"))
    nb = nbformat.read(REPO / "pipeline_demo.ipynb", as_version=4)
    client = nbclient.NotebookClient(
        nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(REPO)}}
    )
    client.execute()  # raises CellExecutionError on the first failing cell
    assert (tmp_path / "out" / "findings.pdf").is_file()
    assert (tmp_path / "out" / "elements" / "elements.PLAN_S.json").is_file()
