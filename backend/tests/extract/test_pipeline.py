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


def test_a_schedule_table_sheet_is_extracted_through_the_pipeline(tmp_path):
    from tests.extract.test_columns_schedule import schedule_pdf

    root = tmp_path / "S"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    schedule_pdf(tmp_path).rename(root / "DA" / "Colonnes" / "COLUMNS-LEVEL-3@4.pdf")
    b = extract_project(root)
    assert b.sheets[0].layout == "shop_schedule_table"
    assert len(b.elements) == 6 and {e.level for e in b.elements} == {"N3"}
    assert {lv.level for lv in b.levels} == {"N3"}


def test_element_ids_are_unique_even_without_a_sheet_id(tmp_path):
    from tests.extract.test_robustness import ES, build_plan  # noqa: F401

    root = tmp_path / "U"
    root.mkdir()
    import pymupdf

    # one plan PDF, two column-plan pages whose sheet id is not in the title block
    pdf_a = build_plan(tmp_path)
    src = pymupdf.open(pdf_a)
    both = pymupdf.open()
    both.insert_pdf(src)
    both.insert_pdf(src)
    both.save(root / "plans.pdf")
    # remove the sheet id so ids cannot come from it
    b = extract_project(
        root,
        config=__import__("dataclasses").replace(
            __import__("l2c.extract.config", fromlist=["DEFAULT_CONFIG"]).DEFAULT_CONFIG,
            sheet_id_pattern=r"^NOPE$",
        ),
    )
    ids = [e.id for e in b.elements]
    # the same four columns are on both pages of one file: they collapse to four elements
    assert len(ids) == 4 and len(set(ids)) == 4


def test_a_failing_ocr_or_learning_step_does_not_stop_the_run(tmp_path, monkeypatch):
    import l2c.extract.pipeline as P

    root = make_project(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(P, "learn_config", boom)
    b = extract_project(root)
    # the failure is recorded per page and the run reaches the end instead of aborting
    assert [s.layout for s in b.sheets] == ["error:RuntimeError", "error:RuntimeError"]


def test_upper_case_pdf_extensions_are_discovered(tmp_path):
    root = make_project(tmp_path)
    (root / "L2C_PLAN_STR_PROJ.pdf").rename(root / "PLAN.PDF")
    found = discover(root)
    assert [p.name for p in found.plans] == ["PLAN.PDF"]


def test_shop_ids_do_not_collide_across_folders_with_the_same_file_name(tmp_path):
    root = tmp_path / "D"
    for sub in ("Colonnes", "Colonnes 2"):
        (root / "DA" / sub).mkdir(parents=True)
        shop_pdf(tmp_path).rename(root / "DA" / sub / "SHEET.pdf")
        # shop_pdf saves to the same temp name each time, so rebuild for the next folder
    b = extract_project(root)
    ids = [e.id for e in b.elements]
    assert len(ids) == len(set(ids)) and len(ids) == 12


def test_multiple_schedule_tables_on_one_sheet_are_reported_not_guessed(tmp_path):
    from tests.extract.pdfmaker import new_doc, put, save

    doc, page = new_doc(1200, 1400)
    for top, title in ((0, "COLUMNS LEVEL2@LEVEL3"), (700, "COLUMNS LEVEL3@LEVEL4")):
        put(page, 700, top + 650, title)
        for x, label in ((150.0, "D-6"), (450.0, "D-7")):
            put(page, x, top + 60, label)
            put(page, x, top + 300, "1x4 25M 25Y1800A")
            put(page, x, top + 400, "1x18 10M 10Q4400 @150")
    root = tmp_path / "M"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    save(doc, root / "DA" / "Colonnes" / "two.pdf")
    b = extract_project(root)
    assert b.elements == []
    assert b.sheets[0].layout == "schedule_multiple_tables_unsupported"


def test_shop_folder_names_come_from_the_config(tmp_path):
    import dataclasses

    from l2c.extract.config import DEFAULT_CONFIG

    es = dataclasses.replace(DEFAULT_CONFIG, folder_types=(("columnas", "colonne"),))
    assert folder_type(("Columnas",), es) == "colonne"
    assert folder_type(("Colonnes",), es) is None


def test_a_parallel_run_gives_byte_identical_output(tmp_path):
    root = make_project(tmp_path)
    a, b = tmp_path / "seq", tmp_path / "par"
    write_bundle(a, extract_project(root, workers=1))
    write_bundle(b, extract_project(root, workers=3))
    for f in sorted(p.name for p in a.iterdir()):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_a_corrupt_pdf_is_still_reported_in_a_parallel_run(tmp_path):
    root = make_project(tmp_path)
    (root / "DA" / "Colonnes" / "broken.pdf").write_bytes(b"%PDF-1.4 this is not a pdf")
    bundle = extract_project(root, workers=2)
    assert any((s.layout or "").startswith("error:open_failed") for s in bundle.sheets)
    assert len([e for e in bundle.elements if e.source == "shop"]) == 6


def _grid_sheet(title: str, statements, name: str, tmp_path, *, with_sheet_id=True):
    from tests.extract.pdfmaker import new_doc, put, save

    doc, page = new_doc(1100, 800)
    for r, y in {"A": 150, "B": 300, "C": 450, "D": 600}.items():
        put(page, 40, y, r)
        put(page, 1000, y, r)
    for c, x in {"1": 150, "2": 400, "3": 650, "4": 900}.items():
        put(page, x, 60, c)
        put(page, x, 740, c)
    put(page, 700, 770, "TITRE DU DESSIN " + title)
    if with_sheet_id:
        put(page, 1050, 770, "S-601")
    for x, y, text in statements:
        put(page, x, y, text)
    return save(doc, tmp_path / name)


def test_beams_walls_slabs_and_foundations_are_extracted_not_skipped(tmp_path):
    root = tmp_path / "T"
    (root / "DA" / "Dalles").mkdir(parents=True)
    (root / "DA" / "Poutres").mkdir(parents=True)
    plan = _grid_sheet(
        "ARMATURE DU NIVEAU 2", [(155, 155, "11-25M"), (405, 305, '10M@6" c/c')], "p.pdf", tmp_path
    )
    plan.rename(root / "plan.pdf")
    shop = _grid_sheet("DALLE", [(155, 155, "11-25M"), (405, 305, '10M@6" c/c')], "s.pdf", tmp_path)
    shop.rename(root / "DA" / "Dalles" / "SHOP_DALLE NIV 2.pdf")
    beam = _grid_sheet("POUTRES", [(155, 155, "4-25M")], "b.pdf", tmp_path)
    beam.rename(root / "DA" / "Poutres" / "SHOP_POUTRES.pdf")
    b = extract_project(root)
    layouts = {s.fichier: s.layout for s in b.sheets}
    assert layouts["plan.pdf"] == "generic_dalle"
    assert layouts["DA/Dalles/SHOP_DALLE NIV 2.pdf"] == "generic_dalle"
    assert layouts["DA/Poutres/SHOP_POUTRES.pdf"] == "generic_poutre"
    types = {(e.source, e.type_element, e.level) for e in b.elements}
    assert ("plan", "dalle", "N2") in types and ("shop", "dalle", "N2") in types
    assert any(e.source == "shop" and e.type_element == "poutre" for e in b.elements)
    ids = [e.id for e in b.elements]
    assert len(ids) == len(set(ids))


def test_typical_details_and_empty_sheets_are_reported_with_a_reason(tmp_path):
    root = tmp_path / "R"
    root.mkdir()
    import pymupdf

    doc = pymupdf.open()
    for title, statements in (
        ("DETAILS TYPIQUES - BETON", [(155, 155, "11-25M")]),
        ("PLAN DU NIVEAU 2", []),
    ):
        src = _grid_sheet(title, statements, f"x{len(doc)}.pdf", tmp_path, with_sheet_id=False)
        doc.insert_pdf(pymupdf.open(src))
    doc.save(root / "plan.pdf")
    b = extract_project(root)
    assert [s.layout for s in b.sheets] == ["typical_details", "no_rebar_annotations"]
    assert b.elements == []
