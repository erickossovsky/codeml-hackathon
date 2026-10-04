import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from l2c.contract import constants as C
from l2c.contract.ids import compress_guid, global_id
from l2c.contract.io import ContractVersionError, MetaBundle, dumps, read_bundle, write_bundle
from l2c.contract.models import (
    Armature,
    ElementExt,
    ElementStrict,
    LocationQuality,
    MatchKey,
    Quality,
)


def make_element(**over) -> ElementExt:
    base = dict(
        id="S-500_C-K6_plan",
        source="plan",
        fichier="plan.pdf",
        feuillet="S-500",
        page=1,
        x=412.5,
        y=318.0,
        type_element="colonne",
        element="D-6",
        armature=[Armature(repere="K6-V", diametre="25M", quantite=4)],
        match_key=MatchKey(type="colonne", level="N2", row="K", col=6),
        grid="D-6",
        level="N2",
        bbox=(400.0, 310.0, 430.0, 326.0),
        quality=Quality(
            overall=0.9,
            type_conf=1.0,
            level_conf=1.0,
            location=LocationQuality(page_xy_conf=1.0, anchor="outline", grid_conf=0.9),
        ),
        extraction_method="rules",
    )
    base.update(over)
    return ElementExt(**base)


def test_strict_projection_has_only_appendix_a_fields():
    strict = make_element().to_strict()
    assert set(strict.model_dump()) == {
        "id",
        "source",
        "fichier",
        "feuillet",
        "page",
        "x",
        "y",
        "type_element",
        "element",
        "armature",
    }


def test_strict_model_rejects_extras():
    with pytest.raises(ValidationError):
        ElementStrict(
            id="a",
            source="plan",
            fichier="f",
            feuillet=None,
            page=1,
            x=0,
            y=0,
            type_element="colonne",
            element="e",
            armature=[],
            bogus=1,
        )


def test_match_key_string_is_stable_and_handles_fractions():
    assert MatchKey(type="colonne", level="N4", row="I", col=13).key_str() == "colonne|N4|I|13"
    assert MatchKey(type="colonne", level="N4", row="A", col=15.8).key_str() == "colonne|N4|A|15.8"
    assert (
        MatchKey(type="poutre", level="N2", row="K", span_from=5, span_to=8).key_str()
        == "poutre|N2|K||5-8"
    )


def test_global_id_deterministic_and_22_chars():
    a = global_id("colonne|N4|I|13")
    assert a == global_id("colonne|N4|I|13")
    assert a != global_id("colonne|N4|I|14")
    assert len(a) == 22
    assert len(compress_guid("0" * 32)) == 22


def test_dumps_is_stable():
    assert dumps({"b": 1, "a": [1, 2]}) == dumps({"a": [1, 2], "b": 1})
    assert dumps({"a": 1}).endswith("\n")


def test_bundle_round_trip_and_strict_file(tmp_path: Path):
    bundle = MetaBundle(project="demo", elements=[make_element()])
    write_bundle(tmp_path, bundle)
    again = read_bundle(tmp_path)
    assert again.elements[0] == bundle.elements[0]
    strict = json.loads((tmp_path / C.FILE_ELEMENTS_STRICT).read_text(encoding="utf-8"))
    assert isinstance(strict, list) and "quality" not in strict[0]
    first = (tmp_path / C.FILE_ELEMENTS_EXT).read_bytes()
    write_bundle(tmp_path, bundle)
    assert first == (tmp_path / C.FILE_ELEMENTS_EXT).read_bytes()  # byte-identical rerun


def test_contract_version_mismatch_fails_loudly(tmp_path: Path):
    write_bundle(tmp_path, MetaBundle(project="demo", elements=[make_element()]))
    manifest = tmp_path / C.FILE_MANIFEST
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["contract_version"] = "9.9.9"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ContractVersionError):
        read_bundle(tmp_path)


def test_committed_json_schemas_match_the_models():
    """If this fails, run `python scripts/export_schemas.py` and commit shared/schemas/ together
    with the model change (a contract PR)."""
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "export_schemas", root / "scripts" / "export_schemas.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from pydantic import TypeAdapter

    for name, tp in mod.SCHEMAS.items():
        committed = json.loads((root / "shared" / "schemas" / name).read_text(encoding="utf-8"))
        assert committed == TypeAdapter(tp).json_schema(), name


def test_duplicate_element_ids_are_refused_loudly(tmp_path: Path):
    bundle = MetaBundle(project="demo", elements=[make_element(), make_element(x=9.0)])
    with pytest.raises(ValueError, match="duplicate element ids"):
        write_bundle(tmp_path, bundle)
