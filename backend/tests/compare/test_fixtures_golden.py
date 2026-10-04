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
