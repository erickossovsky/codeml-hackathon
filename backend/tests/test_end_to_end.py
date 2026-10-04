"""The two lanes together: PDFs -> metadata (extract) -> findings and reports (compare)."""

import json
from pathlib import Path

from l2c.compare.__main__ import main as compare_main
from l2c.contract.io import read_bundle, write_bundle
from l2c.extract.pipeline import extract_project
from tests.extract.test_pipeline import make_project


def run_flow(tmp_path: Path):
    meta, out = tmp_path / "meta", tmp_path / "out"
    write_bundle(meta, extract_project(make_project(tmp_path)))
    assert compare_main([str(meta), "--out", str(out)]) == 0
    return meta, out


def test_extracted_metadata_goes_through_the_comparison_and_produces_every_output(tmp_path):
    meta, out = run_flow(tmp_path)
    assert (out / "findings.json").is_file() and (out / "findings.xlsx").is_file()
    assert (out / "report" / "summary.pdf").is_file()
    assert (out / "report" / "by_plan_sheet.pdf").is_file()
    assert any((out / "comparison").glob("*.json")) and any((out / "comparison").glob("*.pdf"))
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert findings and {f["status"] for f in findings} <= {
        "compliant",
        "non_compliant",
        "missing",
        "added",
        "needs_review",
    }
    assert read_bundle(meta).project == "PROJ"


def test_the_synthetic_project_has_cells_that_match_across_the_lanes(tmp_path):
    _, out = run_flow(tmp_path)
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    cross = [f for f in findings if f["check_type"] == "cross.plan_vs_shop"]
    # plan and shop use the same cells and levels, so some pairs must have been matched
    assert any(f["plan_ref"] and f["shop_ref"] for f in cross)


def test_the_comparison_is_repeatable_on_the_same_metadata(tmp_path):
    meta, out = run_flow(tmp_path)
    again = tmp_path / "again"
    assert compare_main([str(meta), "--out", str(again)]) == 0
    a = (out / "findings.json").read_bytes()
    assert a == (again / "findings.json").read_bytes()
