from l2c.extract.columns_shop import (
    assign_level,
    extract_shop_columns,
    find_level_lines,
    split_views,
)
from l2c.extract.runs import text_runs
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import new_doc, put, save

LEVEL_LINES = [
    ("N4", 100.0, "118' - 4\"", "NIVEAU 4"),
    ("N3", 300.0, "108' - 6\"", "NIVEAU 3"),
    ("N2", 500.0, "98' - 9\"", "NIVEAU 2"),
]
LABELS = {"D-6": 200.0, "D-7": 320.0, "E-7": 440.0}


def shop_pdf(tmp_path, *, drop_label=False):
    doc, page = new_doc(1200, 900)
    for _, y, el, name in LEVEL_LINES:
        put(page, 60, y, f"EL.: {el}")
        put(page, 60, y + 7, name)
    for label, x in LABELS.items():
        if drop_label and label == "E-7":
            continue
        put(page, x, 800, label)
        # upper band (N4..N3 -> level N3) and lower band (N3..N2 -> level N2)
        put(page, x, 130, "VERT: 4 25M B7-01")
        put(page, x, 139, 'ÉTRI: 6 10M T4X21 @6"')
        put(page, x, 330, "VERT: 6 20M B9-02")
        put(page, x, 339, "ÉTRI: 13 10M T2X27")  # no spacing printed, like real sheets
    return save(doc, tmp_path / "COLONNES_P1.pdf")


def test_level_lines_and_bands(tmp_path):
    (page,) = load_pdf(shop_pdf(tmp_path))
    lines = find_level_lines(page, text_runs(page.words))
    assert [line.level for line in lines] == ["N4", "N3", "N2"]
    assert abs(lines[0].elevation_mm - (118 * 304.8 + 4 * 25.4)) < 0.01
    views = split_views(lines)
    assert len(views) == 1
    assert assign_level(views, 130) == ("N3", []) and assign_level(views, 330) == ("N2", [])
    assert assign_level(views, 50) == ("UNKNOWN", ["level_unknown"])
    assert assign_level(views, 900) == ("FDN", ["below_lowest_level"])


def test_two_stacked_elevation_views_do_not_mix_levels(tmp_path):
    doc, page = new_doc(1200, 1400)
    for y, el, name in [
        (100, "108' - 6\"", "NIVEAU 3"),
        (300, "98' - 9\"", "NIVEAU 2"),
        (700, "108' - 6\"", "NIVEAU 3"),
        (900, "98' - 9\"", "NIVEAU 2"),
    ]:
        put(page, 60, y, f"EL.: {el}")
        put(page, 60, y + 7, name)
    (p,) = load_pdf(save(doc, tmp_path / "views.pdf"))
    views = split_views(find_level_lines(p, text_runs(p.words)))
    assert [[line.level for line in v] for v in views] == [["N3", "N2"], ["N3", "N2"]]
    assert assign_level(views, 200) == ("N2", [])  # first view
    assert assign_level(views, 400) == (
        "FDN",
        ["below_lowest_level"],
    )  # below first view's last line
    assert assign_level(views, 800) == ("N2", [])  # second view


def test_extracts_one_element_per_label_and_band(tmp_path):
    (page,) = load_pdf(shop_pdf(tmp_path))
    els, levels = extract_shop_columns(page)
    assert len(els) == 6 and [lv.level for lv in levels] == ["N4", "N3", "N2"]
    k6_n3 = next(e for e in els if e.grid == "D-6" and e.level == "N3")
    assert k6_n3.source == "shop" and k6_n3.feuillet == "COLONNES_P1"
    assert k6_n3.armature[0].quantite == 4 and k6_n3.armature[0].diametre == "25M"
    assert k6_n3.armature[1].quantite == 6 and k6_n3.armature[1].espacement_mm == 152.4
    assert k6_n3.match_key.key_str() == "colonne|N3|D|6"
    assert k6_n3.quality.location.anchor == "label"
    k6_n2 = next(e for e in els if e.grid == "D-6" and e.level == "N2")
    assert k6_n2.armature[1].espacement_mm is None
    assert "spacing_not_on_sheet" in k6_n2.quality.flags
    assert "spacing" not in k6_n2.quality.attributes  # absent, not penalised


def test_no_labels_means_no_elements_but_levels_still_reported(tmp_path):
    doc, page = new_doc()
    put(page, 60, 100, "EL.: 118' - 4\"")
    put(page, 60, 107, "NIVEAU 4")
    put(page, 60, 300, "EL.: 108' - 6\"")
    put(page, 60, 307, "NIVEAU 3")
    (p,) = load_pdf(save(doc, tmp_path / "x.pdf"))
    els, levels = extract_shop_columns(p)
    assert els == [] and len(levels) == 2


def test_blocks_below_the_lowest_level_line_are_foundation_dowels(tmp_path):
    doc, page = new_doc()
    put(page, 60, 100, "EL.: 118' - 4\"")
    put(page, 60, 107, "NIVEAU 4")
    put(page, 60, 300, "EL.: 108' - 6\"")
    put(page, 60, 307, "NIVEAU 3")
    for label, x in {"D-6": 200.0, "D-7": 320.0}.items():
        put(page, x, 800, label)
        put(page, x, 600, "VERT: 4 25M B7-01")  # below the last level line
    (p,) = load_pdf(save(doc, tmp_path / "y.pdf"))
    els, _ = extract_shop_columns(p)
    assert len(els) == 2 and all("below_lowest_level" in e.quality.flags for e in els)
    assert all(e.level == "FDN" and e.quality.overall <= 0.8 for e in els)
