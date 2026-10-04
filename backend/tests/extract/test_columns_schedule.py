from l2c.extract.columns_schedule import extract_schedule_columns, is_schedule_page
from l2c.ingest.pages import Word, load_pdf
from tests.extract.pdfmaker import new_doc, put, save

# three table columns: (cells, vertical spec, ties spec)
TABLE = [
    (["D-6", "D-7", "E-7"], "3x4 25M 25Z2620A", "3x18 10M 10E3752 @150"),
    (["F'-3", "B.1-35.1"], "2x4 30M 30Z2600,", "2x15 10M 10E3752 @175"),
    (["K-9"], "4 25M 25Z2620A", "18 10M 10E3752 @150"),
]
XS = [150.0, 450.0, 750.0]


def schedule_pdf(
    tmp_path, title="COLONNE NIV3@NIV4 PART 1", glue=False, name="COLONNE-NIV-3@4.pdf"
):
    doc, page = new_doc(1200, 900)
    put(page, 700, 850, title)
    for x, (cells, vert, ties) in zip(XS, TABLE, strict=True):
        for i, label in enumerate(cells):
            put(page, x, 60 + 12 * i, label + ("," if i < len(cells) - 1 else ""))
        put(page, x, 300, vert.replace(" ", "") if glue else vert)
        put(page, x, 400, ties)
        put(page, x, 700, f"{len(cells)} REQUIS")
    return save(doc, tmp_path / name)


def test_a_schedule_page_is_recognised(tmp_path):
    (page,) = load_pdf(schedule_pdf(tmp_path))
    assert is_schedule_page(page)


def test_every_listed_cell_gets_the_columns_reinforcement(tmp_path):
    (page,) = load_pdf(schedule_pdf(tmp_path))
    els, levels = extract_schedule_columns(page)
    assert [lv.level for lv in levels] == ["N3"]
    by = {e.grid: e for e in els}
    assert set(by) == {"D-6", "D-7", "E-7", "F'-3", "B.1-35.1", "K-9"}
    d6 = by["D-6"]
    assert d6.source == "shop" and d6.level == "N3" and d6.type_element == "colonne"
    assert d6.armature[0].quantite == 4 and d6.armature[0].diametre == "25M"
    assert d6.armature[1].quantite == 18 and d6.armature[1].espacement_mm == 150.0
    assert d6.match_key.key_str() == "colonne|N3|D|6"
    assert by["B.1-35.1"].match_key.key_str() == "colonne|N3|B.1|35.1"
    assert by["F'-3"].armature[0].diametre == "30M"
    assert by["K-9"].armature[1].espacement_mm == 150.0
    assert "schedule_table" in d6.quality.flags
    assert 0.9 <= d6.quality.overall <= 1.0


def test_glued_ocr_text_is_still_read(tmp_path):
    (page,) = load_pdf(schedule_pdf(tmp_path, glue=True))
    els, _ = extract_schedule_columns(page)
    by = {e.grid: e for e in els}
    assert by["D-6"].armature[0].quantite == 4 and by["E-7"].armature[0].diametre == "25M"


def test_count_of_cells_is_checked_against_the_printed_multiplier(tmp_path):
    doc, page = new_doc(1200, 900)
    put(page, 700, 850, "COLONNE NIV3@NIV4")
    for x, cells, vert, ties in [
        (150.0, ["D-6", "D-7"], "3x4 25M 25Z2620A", "3x18 10M 10E3752 @150"),
        (450.0, ["F-1"], "1x4 25M 25Z2620A", "1x18 10M 10E3752 @150"),
    ]:
        for i, label in enumerate(cells):
            put(page, x, 60 + 12 * i, label)
        put(page, x, 300, vert)
        put(page, x, 400, ties)
    (p,) = load_pdf(save(doc, tmp_path / "mismatch.pdf"))
    els, _ = extract_schedule_columns(p)
    flagged = {e.grid for e in els if "cell_count_mismatch" in e.quality.flags}
    assert flagged == {"D-6", "D-7"}


def test_ocr_confusing_the_letter_i_with_a_one_is_repaired_and_marked(tmp_path):
    doc, page = new_doc(1200, 900)
    put(page, 700, 850, "COLONNE NIV3@NIV4")
    for x in (150.0, 450.0):
        put(page, x, 60, "1.1-34" if x == 150.0 else "D-6")
        put(page, x, 300, "1x4 25M 25Z2620A")
        put(page, x, 400, "1x18 10M 10E3752 @150")
    (p,) = load_pdf(save(doc, tmp_path / "ocr_i.pdf"))
    els, _ = extract_schedule_columns(p)
    fixed = next(e for e in els if e.grid == "I.1-34")
    assert "label_snapped" in fixed.quality.flags and fixed.quality.overall < 1.0


def test_a_page_without_a_level_in_its_title_is_not_a_usable_schedule(tmp_path):
    (page,) = load_pdf(schedule_pdf(tmp_path, title="PART 1", name="sheet.pdf"))
    assert not is_schedule_page(page)


def test_other_pages_are_not_schedules():
    words = [Word("hello", 0, 0, 10, 10)] * 3
    from l2c.ingest.pages import PageData

    page = PageData("x.pdf", 1, 100, 100, 0, words=words)
    assert not is_schedule_page(page)
    assert extract_schedule_columns(page) == ([], [])


def test_the_level_can_come_from_the_file_name_when_the_title_has_none(tmp_path):
    (page,) = load_pdf(schedule_pdf(tmp_path, title="PART 1"))  # file name carries NIV-3@4
    els, levels = extract_schedule_columns(page)
    assert [lv.level for lv in levels] == ["N3"] and len(els) == 6


def test_damaged_tie_lines_are_still_ties_because_of_the_row_they_sit_in(tmp_path):
    doc, page = new_doc(1200, 900)
    put(page, 700, 850, "COLONNE NIV3@NIV4")
    cols = [
        (150.0, "D-6", "3x4 25M 25Z2620A", "3x18 10M 10E3752 @150"),
        (450.0, "D-7", "2x4 25M 25Z2620A", "2x18 10M 10E3752 2@150"),  # stray digit before the @
        (750.0, "E-7", "1x4 25M 25Z2620A", "1x26 10M 10E2752"),  # the @ and spacing were lost
    ]
    for x, label, vert, ties in cols:
        put(page, x, 60, label)
        put(page, x, 300, vert)
        put(page, x, 400, ties)
    (p,) = load_pdf(save(doc, tmp_path / "damaged.pdf"))
    els, _ = extract_schedule_columns(p)
    by = {e.grid: e for e in els}
    assert all(len(e.armature) == 2 for e in els), {g: len(e.armature) for g, e in by.items()}
    assert by["D-7"].armature[1].quantite == 18 and by["D-7"].armature[1].espacement_mm == 150.0
    assert by["E-7"].armature[1].quantite == 26 and by["E-7"].armature[1].espacement_mm is None
    assert by["E-7"].armature[0].quantite == 4
