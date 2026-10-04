"""The extractor must not depend on one project's scale, rotation, language or bar-size system."""

import json

import pytest

from l2c.extract.columns_plan import extract_plan_columns
from l2c.extract.config import DEFAULT_CONFIG, load_config
from l2c.extract.grid import fit_grid
from l2c.extract.notation import canon_level, parse_count_size, plan_column_level
from l2c.extract.pipeline import extract_project
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import DisplayPage, new_doc, put, save

ROWS = {"D": 300.0, "E": 400.0, "F": 500.0, "G": 600.0, "H": 700.0}
COLS = {"6": 500.0, "7": 600.0, "8": 700.0, "9": 800.0, "10": 900.0}
CELLS = [("D", "6"), ("D", "7"), ("E", "7"), ("F", "9")]

FR = dict(
    title="PLAN DES COLONNES - NIVEAU 2",
    arm="ARM.: {n}-{s}",
    lig='LIG.: {t}@6" c/c',
    end="BÉTON: 25MPa / N",
    col='COL. 18"x20"',
)
EN = dict(
    title="COLUMN PLAN - LEVEL 2",
    arm="REINF.: {n}-{s}",
    lig='TIES: {t}@6" c/c',
    end="CONCRETE: 25MPa",
    col='COLUMN 18"x20"',
)
ES = dict(
    title="PLANO DE COLUMNAS - NIVEL 2",
    arm="REFUERZO: {n}-{s}",
    lig='ESTRIBOS: {t}@6" c/c',
    end="HORMIGON: 25MPa",
    col='COLUMNA 18"x20"',
)


def build_plan(tmp_path, *, scale=1.0, rotation=0, words=FR, size="25M", noise=False, grid=True):
    """A synthetic column plan; every distance and font size is multiplied by `scale`."""
    s = scale
    dp = DisplayPage(1200 * s, 900 * s, rotation)
    fs = 8.0 * s
    if grid:
        for letter, y in ROWS.items():
            dp.put(40 * s, y * s, letter, fs)
            dp.put(1100 * s, y * s, letter, fs)
        for label, x in COLS.items():
            dp.put(x * s, 60 * s, label, fs)
            dp.put(x * s, 820 * s, label, fs)
    dp.put(1050 * s, 860 * s, "S-517", fs)
    dp.put(300 * s, 40 * s, words["title"], fs)
    for r, c in CELLS:
        cx, cy = COLS[c] * s + 2 * s, ROWS[r] * s + 4 * s
        if grid:
            dp.rect(cx, cy, 12 * s, 18 * s)
        x, y = cx + 35 * s, cy + 20 * s
        dp.put(x, y - 9 * s, words["col"], fs)
        dp.put(x, y, words["arm"].format(n=4, s=size), fs)
        dp.put(x, y + 9 * s, words["lig"].format(t="10M" if size.endswith("M") else "#3"), fs)
        dp.put(x, y + 18 * s, words["end"], fs)
    if noise:
        for i in range(30):
            dp.put((50 + 33 * i) * s, (120 + 7 * (i % 9)) * s, f"NOTE {i} SEE DETAIL", fs)
            dp.rect(
                (70 + 31 * i) * s, (150 + 11 * (i % 5)) * s, 40 * s, 3 * s
            )  # thin lines, not columns
    return dp.save(tmp_path / f"plan_{scale}_{rotation}.pdf")


def extract(pdf, config=DEFAULT_CONFIG):
    (page,) = load_pdf(pdf, config=config)
    level = plan_column_level(" ".join(w.text for w in page.words), config)
    grid = fit_grid(page.words, config)
    return page, level, extract_plan_columns(page, level, grid, config)


def signature(els):
    return sorted(
        (e.grid, e.armature[0].quantite, e.armature[0].diametre, e.armature[1].espacement_mm)
        for e in els
        if e.grid
    )


EXPECTED = sorted((f"{r}-{c}", 4, "25M", 152.4) for r, c in CELLS)


@pytest.mark.parametrize("scale", [0.25, 0.5, 1.0, 2.5, 4.0])
def test_drawing_scale_does_not_matter(tmp_path, scale):
    _, level, els = extract(build_plan(tmp_path, scale=scale))
    assert level == "N2" and signature(els) == EXPECTED


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_stored_page_rotation_does_not_matter(tmp_path, rotation):
    page, level, els = extract(build_plan(tmp_path, rotation=rotation))
    assert (page.width, page.height) == (1200, 900)  # always the displayed size
    assert level == "N2" and signature(els) == EXPECTED


@pytest.mark.parametrize("words", [FR, EN])
def test_french_and_english_work_with_the_default_config(tmp_path, words):
    _, level, els = extract(build_plan(tmp_path, words=words))
    assert level == "N2" and signature(els) == EXPECTED


def test_another_language_needs_only_a_json_config(tmp_path):
    cfg = tmp_path / "es.json"
    cfg.write_text(
        json.dumps(
            {
                "plan_column_titles": ["PLANO DE COLUMNAS"],
                "block_start": ["REFUERZO"],
                "section_line": ["COLUMNA "],
                "ties_line": ["ESTRIBOS"],
                "end_line": ["HORMIGON"],
                "level_numbered": ["NIVEL"],
            }
        ),
        encoding="utf-8",
    )
    pdf = build_plan(tmp_path, words=ES)
    _, level_default, els_default = extract(pdf)
    assert level_default is None and els_default == [] or signature(els_default) != EXPECTED
    _, level, els = extract(pdf, load_config(cfg))
    assert level == "N2" and signature(els) == EXPECTED


def test_unknown_config_keys_are_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"not_a_setting": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown config keys"):
        load_config(bad)


def test_a_different_bar_size_system_is_a_config_change(tmp_path):
    cfg = tmp_path / "us.json"
    cfg.write_text(
        json.dumps({"bar_size_pattern": r"#\d{1,2}", "bar_sizes": ["#4", "#5", "#8"]}),
        encoding="utf-8",
    )
    config = load_config(cfg)
    assert parse_count_size("ARM.: 4-#8", config).size == "#8"
    assert parse_count_size("ARM.: 4-25M", config) is None
    _, _, els = extract(build_plan(tmp_path, size="#8"), config)
    assert [e.armature[0].diametre for e in els if e.grid] == ["#8"] * 4


def test_noise_text_and_thin_shapes_do_not_change_the_result(tmp_path):
    _, _, els = extract(build_plan(tmp_path, noise=True))
    assert signature(els) == EXPECTED and len(els) == 4


def test_spacing_unit_default_is_configurable():
    from l2c.extract.notation import parse_size_spacing

    mm = load_config(None)
    assert parse_size_spacing("10M@150", mm).spacing_mm == 150.0  # 30 or more cannot be inches
    assert parse_size_spacing("10M@6", mm).spacing_mm == pytest.approx(152.4)  # inches by default
    metric = type(mm)(default_spacing_unit="mm")
    assert parse_size_spacing("10M@150", metric).spacing_mm == 150.0
    assert parse_size_spacing('10M@6"', metric).spacing_mm == pytest.approx(152.4)


def test_level_names_in_other_conventions():
    assert canon_level("Basement") == "SS" and canon_level("LEVEL 12") == "N12"
    assert canon_level("Étage 3") is None  # unknown word: reported, not guessed


def make_project(tmp_path, plan_pdf_path):
    root = tmp_path / "P"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    plan_pdf_path.rename(root / "plan.pdf")
    return root


def test_grid_missing_is_reported_not_guessed(tmp_path):
    root = make_project(tmp_path, build_plan(tmp_path, grid=False))
    b = extract_project(root)
    assert b.sheets[0].layout == "plan_blocks_without_grid"
    assert len(b.elements) == 4 and all("unbound_block" in e.quality.flags for e in b.elements)


def test_unreadable_pages_are_labelled_with_the_reason(tmp_path):
    doc, page = new_doc()
    for i in range(300):
        page.draw_line((10, 10 + i), (500, 12 + i))  # many paths, no text: a vector-only sheet
    root = tmp_path / "P"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    save(doc, root / "DA" / "Colonnes" / "vec.pdf")
    doc2, page2 = new_doc()
    save(doc2, root / "DA" / "Colonnes" / "empty.pdf")
    layouts = {s.fichier: s.layout for s in extract_project(root).sheets}
    assert layouts["DA/Colonnes/vec.pdf"] == "needs_ocr"
    assert layouts["DA/Colonnes/empty.pdf"] == "empty_page"


def test_a_failing_page_does_not_stop_the_run(tmp_path, monkeypatch):
    import l2c.extract.pipeline as P

    root = make_project(tmp_path, build_plan(tmp_path))

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(P, "extract_plan_columns", boom)
    b = extract_project(root)
    assert b.sheets[0].layout == "error:RuntimeError" and b.elements == []


def test_unsupported_folder_types_are_covered_in_sheets_not_elements(tmp_path):
    root = tmp_path / "P"
    (root / "DA" / "Divers").mkdir(parents=True)
    doc, page = new_doc()
    put(page, 100, 100, "SOMETHING " * 5)
    save(doc, root / "DA" / "Divers" / "notes.pdf")
    b = extract_project(root)
    assert b.elements == [] and b.sheets[0].layout == "type_not_supported:unknown"


def test_a_shop_sheet_without_any_level_marks_is_reported_not_emitted_as_unusable_elements(
    tmp_path,
):
    root = tmp_path / "P"
    (root / "DA" / "Colonnes").mkdir(parents=True)
    dp = DisplayPage(1200, 900)
    for label, x in {"D-6": 200.0, "D-7": 360.0, "E-7": 520.0}.items():
        dp.put(x, 800, label)
        for y in (130, 330):
            dp.put(x, y, "VERT: 4 25M V7-A")
            dp.put(x, y + 9, 'ETRI: 6 10M T4X21 @6"')
    dp.save(root / "DA" / "Colonnes" / "nolevels.pdf")
    b = extract_project(root)
    assert b.elements == [] and b.sheets[0].layout == "shop_levels_not_found"
