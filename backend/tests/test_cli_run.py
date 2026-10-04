import json

from l2c.__main__ import main
from tests.extract.test_pipeline import make_project


def test_l2c_run_does_the_whole_flow_and_writes_the_outputs(tmp_path):
    out = tmp_path / "out"
    assert main(["run", str(make_project(tmp_path)), "--out", str(out), "--workers", "1"]) == 0
    assert (out / "metadata" / "elements.json").is_file()
    assert (out / "compare" / "findings.json").is_file()
    assert (out / "compare" / "report" / "summary.pdf").is_file()
    assert json.loads((out / "compare" / "findings.json").read_text(encoding="utf-8"))


def test_an_unknown_command_is_refused(capsys):
    assert main(["fly"]) == 2
