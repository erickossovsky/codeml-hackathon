"""Labels in an invented language are learned from the notation around them."""

import dataclasses

from l2c.extract.columns_plan import extract_plan_columns
from l2c.extract.config import DEFAULT_CONFIG
from l2c.extract.grid import fit_grid
from l2c.extract.learn import learn_config, learn_keywords
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import DisplayPage

ROWS = {"A": 300.0, "B": 400.0, "C": 500.0, "D": 600.0, "E": 700.0}
COLS = {"1": 500.0, "2": 600.0, "3": 700.0, "4": 800.0, "5": 900.0}
CELLS = [("A", "1"), ("A", "2"), ("B", "2"), ("C", "4"), ("D", "5")]

# an invented vocabulary no default dictionary contains
WORDS = dict(bar="ZORB", tie="KLEM", sect="QUAD", end="FINX", title="PLAN DES COLONNES - NIVEAU 2")


def invented_plan(tmp_path):
    dp = DisplayPage(1200, 900)
    for letter, y in ROWS.items():
        dp.put(40, y, letter)
        dp.put(1100, y, letter)
    for label, x in COLS.items():
        dp.put(x, 60, label)
        dp.put(x, 820, label)
    dp.put(300, 40, WORDS["title"])
    dp.put(1050, 860, "S-517")
    for r, c in CELLS:
        cx, cy = COLS[c] + 2, ROWS[r] + 4
        dp.rect(cx, cy)
        x, y = cx + 35, cy + 20
        dp.put(x, y - 9, f'{WORDS["sect"]} 18"x20"')
        dp.put(x, y, f"{WORDS['bar']}: 4-25M")
        dp.put(x, y + 9, f'{WORDS["tie"]}: 10M@6" c/c')
        dp.put(x, y + 18, f"{WORDS['end']}: 25MPa")
    dp.put(100, 150, "TYP: 4-25M")  # a one-off label must not be learned
    return dp.save(tmp_path / "invented.pdf")


def test_unknown_labels_are_learned_from_the_notation_around_them(tmp_path):
    (page,) = load_pdf(invented_plan(tmp_path))
    learned = learn_keywords(page.words)
    assert learned["block_start"] == ("ZORB",)
    assert learned["ties_line"] == ("KLEM",)
    assert learned["section_line"] == ("QUAD",)
    assert "TYP" not in learned["block_start"]  # appears once: below the occurrence minimum


def test_without_learning_the_default_dictionary_finds_nothing(tmp_path):
    (page,) = load_pdf(invented_plan(tmp_path))
    assert extract_plan_columns(page, "N2", fit_grid(page.words)) == []


def test_with_learning_the_same_page_extracts_every_column(tmp_path):
    (page,) = load_pdf(invented_plan(tmp_path))
    config = learn_config(page.words)
    els = extract_plan_columns(page, "N2", fit_grid(page.words, config), config)
    assert sorted(e.grid for e in els) == ["A-1", "A-2", "B-2", "C-4", "D-5"]
    assert all(e.armature[0].quantite == 4 and e.armature[1].espacement_mm == 152.4 for e in els)


def test_known_labels_are_not_duplicated_and_the_config_is_unchanged_when_nothing_is_new(tmp_path):
    from tests.extract.test_columns_plan import plan_pdf

    (page,) = load_pdf(plan_pdf(tmp_path))
    assert learn_keywords(page.words) == {}
    assert learn_config(page.words) is DEFAULT_CONFIG


def test_learning_is_deterministic_and_does_not_mutate_the_default(tmp_path):
    (page,) = load_pdf(invented_plan(tmp_path))
    a, b = learn_config(page.words), learn_config(page.words)
    assert a == b and dataclasses.is_dataclass(a)
    assert "ZORB" not in DEFAULT_CONFIG.block_start


def test_a_page_without_notation_learns_nothing():
    assert learn_keywords([]) == {}


def test_the_pipeline_learns_by_default_and_can_be_told_not_to(tmp_path):
    from l2c.extract.pipeline import extract_project

    root = tmp_path / "P"
    root.mkdir()
    invented_plan(tmp_path).rename(root / "plan.pdf")
    learned = extract_project(root)
    assert sorted(e.grid for e in learned.elements) == ["A-1", "A-2", "B-2", "C-4", "D-5"]
    assert learned.sheets[0].layout == "plan_outline"
    off = extract_project(root, learn=False)
    assert off.elements == []


def test_a_label_is_never_learned_for_two_roles(tmp_path):
    """A tie line without a printed spacing has the shape of a vertical-bar line; it must not be
    learned as one, or every tie line would be read twice."""
    dp = DisplayPage(1200, 900)
    for x in (100, 300, 500, 700, 900):
        dp.put(x, 100, "QWERT: 4 25M B7-01")
        dp.put(x, 109, 'ZIGZAG: 6 10M T3X21 @6"')
        dp.put(x, 300, "QWERT: 4 25M B7-02")
        dp.put(x, 309, "ZIGZAG: 13 10M T3X18")  # no spacing printed
    (page,) = load_pdf(dp.save(tmp_path / "shop_roles.pdf"))
    learned = learn_keywords(page.words)
    assert learned.get("shop_vert") == ("QWERT",)
    assert "ZIGZAG" not in learned.get("shop_vert", ())
    assert learned.get("shop_ties") == ("ZIGZAG",)
