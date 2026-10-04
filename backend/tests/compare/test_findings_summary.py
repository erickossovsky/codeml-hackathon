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
