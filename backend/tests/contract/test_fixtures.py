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
