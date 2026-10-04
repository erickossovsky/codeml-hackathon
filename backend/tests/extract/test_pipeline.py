import json
import subprocess
import sys
from pathlib import Path

import jsonschema

from l2c.contract.io import read_bundle, write_bundle
from l2c.extract.pipeline import discover, extract_project, folder_type
from tests.extract.test_columns_plan import plan_pdf
from tests.extract.test_columns_shop import shop_pdf

SCHEMAS = Path(__file__).resolve().parents[3] / "shared" / "schemas"


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "PROJ"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    (root / "DA" / "Dalles").mkdir(parents=True)
    plan = plan_pdf(tmp_path)
    plan.rename(root / "L2C_PLAN_STR_PROJ.pdf")
    shop = shop_pdf(tmp_path)
    shop.rename(root / "DA" / "Colonnes" / "COLONNES P1.pdf")
    return root


def test_folder_type_mapping():
    assert folder_type(("Colonnes",)) == "colonne"
    assert folder_type(("Semelles et radiers",)) == "fondation"
    assert folder_type(("Murs refends",)) == "mur_refend"
    assert folder_type(("Autre",)) is None


def test_discovery_is_sorted_and_typed(tmp_path):
    found = discover(make_project(tmp_path))
    assert [p.name for p in found.plans] == ["L2C_PLAN_STR_PROJ.pdf"]
    assert [(p.name, t) for p, t in found.shops] == [("COLONNES P1.pdf", "colonne")]


def test_extract_project_end_to_end(tmp_path):
    bundle = extract_project(make_project(tmp_path))
    plan = [e for e in bundle.elements if e.source == "plan"]
    shop = [e for e in bundle.elements if e.source == "shop"]
    assert len(plan) == 4 and len(shop) == 6
    assert {lv.level for lv in bundle.levels} >= {"N2", "N3", "N4"}
    assert bundle.sheets[0].type_element == "colonne" and bundle.sheets[0].level == "N2"
    assert len(bundle.grids) == 1
    assert {e.fichier for e in shop} == {"DA/Colonnes/COLONNES P1.pdf"}


def test_bundle_files_validate_against_exported_schemas(tmp_path):
    out = tmp_path / "meta"
    write_bundle(out, extract_project(make_project(tmp_path)))
    for data_file, schema_file in [
        ("elements.json", "elements.schema.json"),
        ("elements.ext.json", "elements.ext.schema.json"),
        ("grid.json", "grid.schema.json"),
        ("levels.json", "levels.schema.json"),
        ("sheets.json", "sheets.schema.json"),
        ("ids.json", "ids.schema.json"),
        ("manifest.json", "manifest.schema.json"),
    ]:
        data = json.loads((out / data_file).read_text(encoding="utf-8"))
        schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
    strict = json.loads((out / "elements.json").read_text(encoding="utf-8"))
    assert all(
        set(r)
        == {
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
        for r in strict
    )
    assert read_bundle(out).project == "PROJ"


def test_two_runs_are_byte_identical(tmp_path):
    root = make_project(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    write_bundle(a, extract_project(root))
    write_bundle(b, extract_project(root))
    for f in sorted(p.name for p in a.iterdir()):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_cli_prints_counts_only(tmp_path):
    root = make_project(tmp_path)
    out = tmp_path / "cli"
    r = subprocess.run(
        [sys.executable, "-m", "l2c.extract", str(root), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("elements=10 plan=4 shop=6")
    assert "plan_outline" in r.stdout and "shop_label_strip" in r.stdout
    assert "25M" not in r.stdout and "D-6" not in r.stdout  # no drawing values on stdout


def test_empty_project_and_missing_folders_do_not_crash(tmp_path):
    empty = tmp_path / "EMPTY"
    empty.mkdir()
    b = extract_project(empty)
    assert b.elements == [] and b.sheets == [] and b.project == "EMPTY"
    only_plan = tmp_path / "ONLYPLAN"
    only_plan.mkdir()
    plan_pdf(tmp_path).rename(only_plan / "plan.pdf")
    b2 = extract_project(only_plan)  # no DA folder at all
    assert len(b2.elements) == 4 and all(e.source == "plan" for e in b2.elements)


def test_file_names_with_spaces_and_accents_work(tmp_path):
    root = tmp_path / "Projet Été"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    plan_pdf(tmp_path).rename(root / "Plan Structure – Étage 2.pdf")
    shop_pdf(tmp_path).rename(root / "DA" / "Colonnes" / "COLONNES Édition 1 (révisé).pdf")
    out = tmp_path / "meta"
    write_bundle(out, extract_project(root))
    bundle = read_bundle(out)
    assert {e.fichier for e in bundle.elements if e.source == "shop"} == {
        "DA/Colonnes/COLONNES Édition 1 (révisé).pdf"
    }
    assert any("Étage 2" in e.fichier for e in bundle.elements if e.source == "plan")


def test_a_corrupt_pdf_is_reported_and_the_rest_of_the_run_continues(tmp_path):
    root = make_project(tmp_path)
    (root / "DA" / "Colonnes" / "broken.pdf").write_bytes(b"%PDF-1.4 this is not a pdf")
    (root / "DA" / "Colonnes" / "empty.pdf").write_bytes(b"")
    b = extract_project(root)
    bad = {s.fichier: s.layout for s in b.sheets if s.layout and s.layout.startswith("error:")}
    assert set(bad) == {"DA/Colonnes/broken.pdf", "DA/Colonnes/empty.pdf"}
    assert all(v.startswith("error:open_failed:") for v in bad.values())
    assert len([e for e in b.elements if e.source == "shop"]) == 6  # the good file still ran
