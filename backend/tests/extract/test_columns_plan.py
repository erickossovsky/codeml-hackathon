from l2c.extract.columns_plan import assemble_blocks, extract_plan_columns
from l2c.extract.grid import fit_grid
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import new_doc, put, rect, save

ROWY = {"D": 300.0, "E": 400.0, "F": 500.0, "G": 600.0, "H": 700.0}
COLX = {"6": 500.0, "7": 600.0, "8": 700.0, "9": 800.0, "10": 900.0}


def center(row: str, col: str) -> tuple[float, float]:
    return COLX[col] + 2, ROWY[row] + 4


def block(page, row, col, arm="ARM.: 4-25M", lig='LIG.: 10M@6" c/c', dx=35.0, dy=20.0):
    cx, cy = center(row, col)
    x, y = cx + dx, cy + dy
    put(page, x, y - 9, 'COL. 18"x20"')
    put(page, x, y, arm)
    put(page, x, y + 9, lig)
    put(page, x, y + 18, "BÉTON: 25MPa / N")


def plan_pdf(tmp_path, *, with_outline=True, extra=None):
    doc, page = new_doc(1200, 900)
    for letter, y in ROWY.items():
        put(page, 40, y, letter)
        put(page, 1100, y, letter)
    for label, x in COLX.items():
        put(page, x, 60, label)
        put(page, x, 820, label)
    put(page, 1050, 860, "S-517")
    put(page, 300, 40, "PLAN DES COLONNES - NIVEAU 2")
    cells = [("D", "6"), ("D", "7"), ("E", "7"), ("F", "9")]
    for r, c in cells:
        if with_outline:
            rect(page, *center(r, c))
        outlier = (r, c) == ("E", "7")
        block(
            page,
            r,
            c,
            arm="ARM.: 4-35M +GOUJ." if outlier else "ARM.: 4-25M",
            lig='LIG.: 10M@8" c/c' if outlier else 'LIG.: 10M@6" c/c',
        )
    if extra:
        extra(page)
    return save(doc, tmp_path / "plan.pdf")


def test_blocks_are_assembled_per_arm_run(tmp_path):
    (page,) = load_pdf(plan_pdf(tmp_path))
    blocks = assemble_blocks(page)
    assert len(blocks) == 4
    assert all(b.col is not None and b.lig is not None for b in blocks)
    assert "BÉTON" in blocks[0].text


def test_extracts_columns_with_correct_cells_even_when_blocks_sit_beside_neighbours(tmp_path):
    (page,) = load_pdf(plan_pdf(tmp_path))
    grid = fit_grid(page.words)
    els = extract_plan_columns(page, "N2", grid)
    by_grid = {e.grid: e for e in els}
    assert set(by_grid) == {"D-6", "D-7", "E-7", "F-9"}
    odd = by_grid["E-7"]
    assert odd.armature[0].quantite == 4 and odd.armature[0].diametre == "35M"
    assert odd.armature[1].espacement_mm == 203.2
    assert "dowels_noted" in odd.quality.flags
    assert odd.match_key.key_str() == "colonne|N2|E|7"
    assert odd.section_mm == (457.2, 508.0)
    typical = by_grid["D-6"]
    assert typical.armature[0].diametre == "25M" and typical.armature[1].espacement_mm == 152.4
    assert typical.quality.location.anchor == "outline"
    assert 0.9 <= typical.quality.overall <= 1.0
    assert (
        typical.id == "S-517_D-6_plan" and typical.feuillet == "S-517" and typical.source == "plan"
    )


def test_blocks_without_outlines_are_kept_but_flagged_unbound(tmp_path):
    (page,) = load_pdf(plan_pdf(tmp_path, with_outline=False))
    els = extract_plan_columns(page, "N2", fit_grid(page.words))
    assert len(els) == 4
    assert all("unbound_block" in e.quality.flags for e in els)
    assert all(e.match_key.row is None and e.quality.overall <= 0.1 for e in els)


def test_unparseable_block_gets_missing_attributes_and_low_quality(tmp_path):
    def bad(page):
        put(page, 500 + 35, 700 + 4 + 20, "ARM.: ??")

    (page,) = load_pdf(plan_pdf(tmp_path, extra=bad))
    els = extract_plan_columns(page, "N2", fit_grid(page.words))
    broken = [e for e in els if "count_unparsed" in e.quality.flags]
    assert len(broken) == 1 and broken[0].quality.overall <= 0.3
    assert broken[0].armature[0].quantite is None


def test_extraction_is_deterministic(tmp_path):
    (page,) = load_pdf(plan_pdf(tmp_path))
    g = fit_grid(page.words)
    a = [e.model_dump_json() for e in extract_plan_columns(page, "N2", g)]
    b = [e.model_dump_json() for e in extract_plan_columns(page, "N2", g)]
    assert a == b
