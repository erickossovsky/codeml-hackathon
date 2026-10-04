from l2c.extract.generic import extract_footings
from l2c.extract.grid import fit_grid
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import new_doc, put, save

SCHEDULE = [
    ("A", "15'-10\"", "2'-8\"", "17-25M", "17-25M"),
    ("B", "12'-6\"", "2'-2\"", "11-25M", "11-25M"),
    ("C", "11'-1\"", "2'-0\"", "9-25M", "9-25M"),
]


def footing_page(tmp_path, footings, schedule=SCHEDULE, name="foot.pdf"):
    doc, page = new_doc(1100, 800)
    for r, y in {"A": 150, "B": 300, "C": 450, "D": 600}.items():
        put(page, 40, y, r)
        put(page, 1000, y, r)
    for c, x in {"1": 150, "2": 400, "3": 650, "4": 900}.items():
        put(page, x, 60, c)
        put(page, x, 740, c)
    x0, y0 = 700, 40
    put(page, x0, y0, "TYPE")
    put(page, x0 + 60, y0, "LONGUEUR")
    put(page, x0 + 180, y0, "ARM.")
    put(page, x0 + 240, y0, "ARM.")
    for i, (t, lo, la, al, at) in enumerate(schedule):
        y = y0 + 14 + 12 * i
        put(page, x0, y, t)
        put(page, x0 + 60, y, lo)
        put(page, x0 + 180, y, al)
        put(page, x0 + 240, y, at)
    for x, y, letter in footings:
        put(page, x, y, letter)
    return load_pdf(save(doc, tmp_path / name))[0]


def test_each_footing_takes_the_bars_of_its_type_from_the_schedule(tmp_path):
    page = footing_page(tmp_path, [(155, 155, "C"), (405, 305, "B")])
    els = extract_footings(page, "N2", fit_grid(page.words), "plan")
    by = {e.grid: e for e in els}
    assert set(by) == {"A-1", "B-2"}
    c = by["A-1"]
    assert c.type_element == "fondation" and c.level == "N2"
    assert {(a.quantite, a.diametre) for a in c.armature} == {(9, "25M")}
    assert c.provenance["footing_type"] == "C"
    assert {(a.quantite, a.diametre) for a in by["B-2"].armature} == {(11, "25M")}


def test_a_footing_without_a_schedule_row_is_kept_and_flagged(tmp_path):
    page = footing_page(tmp_path, [(155, 155, "Z")])  # type Z is not in the schedule
    (e,) = extract_footings(page, "N2", fit_grid(page.words), "plan")
    assert "type_not_in_schedule" in e.quality.flags and e.armature == []


def test_no_schedule_means_no_footing_elements(tmp_path):
    page = footing_page(tmp_path, [(155, 155, "C")], schedule=[])
    assert extract_footings(page, "N2", fit_grid(page.words), "plan") == []
