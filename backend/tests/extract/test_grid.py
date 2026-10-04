from l2c.extract.grid import Grid, fit_grid
from l2c.extract.runs import text_runs
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import new_doc, put, save

ROWS = {"A": 700, "B": 640, "C": 560, "D": 480, "E": 400, "F": 300}
COLS = {"1": 900, "2": 850, "3": 790, "3.8": 740, "4": 690, "5": 600, "6": 543}


def grid_pdf(tmp_path):
    doc, page = new_doc(1100, 800)
    for letter, y in ROWS.items():
        put(page, 40, y, letter)
        put(page, 1000, y, letter)  # same letters on the opposite edge
    for label, x in COLS.items():
        put(page, x, 40, label)
        put(page, x, 760, label)
    put(page, 500, 400, "ARM.: 4-25M")  # noise
    return save(doc, tmp_path / "grid.pdf")


def test_fit_grid_finds_rows_cols_and_fractional_lines(tmp_path):
    (page,) = load_pdf(grid_pdf(tmp_path))
    grid = fit_grid(page.words)
    assert grid is not None
    assert set(grid.rows) == set(ROWS) and set(grid.cols) == set(COLS)
    assert abs(grid.rows["C"] - (560 + 4)) < 3
    assert abs(grid.cols["3.8"] - (740 + 6)) < 8  # label center, not left edge


def test_fit_grid_requires_enough_labels(tmp_path):
    doc, page = new_doc()
    put(page, 40, 100, "A")
    put(page, 100, 40, "1")
    (p,) = load_pdf(save(doc, tmp_path / "few.pdf"))
    assert fit_grid(p.words) is None


def test_snap_confidence_drops_when_between_close_gridlines():
    g = Grid(rows={"A": 100.0, "B": 200.0}, cols={"3.4": 1400.0, "4": 1352.0})
    exact = g.snap(1352.0, 100.0, 14.0)
    assert exact == ("A", "4", 1.0)
    ambiguous = g.snap(1376.0, 104.0, tol=30.0)  # halfway between two close gridlines
    assert ambiguous is not None and ambiguous[1] in {"3.4", "4"} and ambiguous[2] < 0.1
    assert g.snap(1376.0, 104.0, 14.0) is None  # default tolerance rejects a point on neither line
    assert g.snap(900.0, 100.0, 14.0) is None  # too far from any gridline


def test_text_runs_split_on_gaps(tmp_path):
    doc, page = new_doc()
    put(page, 100, 100, "ARM.: 4-25M")
    put(page, 300, 100, "ARM.: 6-20M")
    (p,) = load_pdf(save(doc, tmp_path / "runs.pdf"))
    runs = text_runs(p.words)
    assert [r.text for r in runs] == ["ARM.: 4-25M", "ARM.: 6-20M"]


def test_rows_may_continue_past_z_and_noise_letters_are_ignored(tmp_path):
    doc, page = new_doc(1100, 800)
    rows = ["X", "Y", "Z", "AA", "BB", "CC"]
    for i, r in enumerate(rows):
        put(page, 40, 100 + 80 * i, r)
        put(page, 1000, 100 + 80 * i, r)
    for i in range(1, 8):
        put(page, 100 * i, 40, str(i))
        put(page, 100 * i, 740, str(i))
    for i in range(30):  # many identical noise letters, like "/ N" in concrete notes
        put(page, 200 + 7 * i, 300 + 11 * (i % 5), "N")
    (p,) = load_pdf(save(doc, tmp_path / "wide.pdf"))
    grid = fit_grid(p.words)
    assert grid is not None and list(grid.rows) == rows
    assert len(grid.cols) == 7


def transposed_grid_pdf(tmp_path, noise=True):
    """Letters along the top edge, numbers down the side: the opposite of the first convention."""
    doc, page = new_doc(1400, 900)
    letters = ["A", "B", "C", "D", "E", "F", "G"]
    for i, ch in enumerate(letters):
        put(page, 150 + 150 * i, 40, ch)
    for i in range(1, 7):
        put(page, 40, 100 + 110 * i, str(i))
        put(page, 1300, 100 + 110 * i, str(i))  # mirrored on the opposite edge
    if noise:
        for i in range(25):
            put(page, 300 + 9 * i, 200 + 13 * (i % 7), str(i % 9 + 1))
    return save(doc, tmp_path / "transposed.pdf")


def test_transposed_grid_is_detected_with_its_orientation(tmp_path):
    (p,) = load_pdf(transposed_grid_pdf(tmp_path))
    grid = fit_grid(p.words)
    assert grid is not None and grid.letters_on == "x"
    assert list(grid.rows) == ["A", "B", "C", "D", "E", "F", "G"]
    assert list(grid.cols) == ["1", "2", "3", "4", "5", "6"]
    x, y = grid.center("C", "3")
    assert abs(x - (150 + 300 + 2)) < 8 and abs(y - (100 + 330 + 4)) < 8
    assert grid.snap(x + 3, y - 2, 14.0)[:2] == ("C", "3")


def test_the_usual_convention_still_reports_letters_on_y(tmp_path):
    (p,) = load_pdf(grid_pdf(tmp_path))
    assert fit_grid(p.words).letters_on == "y"


def test_fractional_rows_are_kept_in_order_between_their_neighbours(tmp_path):
    doc, page = new_doc(1100, 800)
    rows = {"A": 100, "A.5": 160, "B": 240, "C": 330, "D": 420}
    for r, y in rows.items():
        put(page, 40, y, r)
        put(page, 1000, y, r)
    for i in range(1, 6):
        put(page, 100 * i, 40, str(i))
        put(page, 100 * i, 740, str(i))
    (p,) = load_pdf(save(doc, tmp_path / "frac.pdf"))
    grid = fit_grid(p.words)
    assert grid is not None and list(grid.rows) == list(rows)


def test_repeated_identical_letters_in_a_row_do_not_beat_the_real_axis(tmp_path):
    """Annotation rows repeat one letter many times and each copy has a twin far away; the real
    axis is a long run of distinct, increasing labels even when it is not mirrored."""
    doc, page = new_doc(1400, 900)
    letters = ["A", "B", "C", "D", "E", "F", "G", "H"]
    for i, ch in enumerate(letters):
        put(page, 100 + 120 * i, 40, ch)  # the real axis along the top, not mirrored
    for i in range(1, 7):
        put(page, 40, 100 + 110 * i, str(i))
        put(page, 1300, 100 + 110 * i, str(i))
    for row_y in (300, 500):  # two annotation rows of identical letters, like "/ N" in notes
        for k in range(9):
            put(page, 100 + 130 * k, row_y, "N")
    (p,) = load_pdf(save(doc, tmp_path / "noisy_axis.pdf"))
    grid = fit_grid(p.words)
    assert grid is not None and grid.letters_on == "x"
    assert list(grid.rows) == letters


def test_wider_centred_labels_stay_on_the_axis(tmp_path):
    """Grid bubbles centre their text, so `A.5` starts further left than `A` on the same line."""
    doc, page = new_doc(1100, 800)
    rows = {"A": 100, "A.5": 160, "B": 240, "C": 330, "D": 420}
    for r, y in rows.items():
        x = 40 - 2.2 * (len(r) - 1)  # centred on x = 40 (Helvetica 8 pt is about 4.4 pt a letter)
        put(page, x, y, r)
        put(page, 1000 - 2.2 * (len(r) - 1), y, r)
    for i in range(1, 6):
        put(page, 100 * i, 40, str(i))
        put(page, 100 * i, 740, str(i))
    (p,) = load_pdf(save(doc, tmp_path / "centred.pdf"))
    grid = fit_grid(p.words)
    assert grid is not None and list(grid.rows) == list(rows)
