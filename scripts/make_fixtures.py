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
