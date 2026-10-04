import pytest

from l2c.extract import notation as N


def test_count_size():
    assert N.parse_count_size("ARM.: 4-25M") == N.CountSize(4, "25M")
    assert N.parse_count_size("ARM.: 12 - 35M +GOUJ.") == N.CountSize(12, "35M")
    assert N.parse_count_size("ARM.: 4-26M") is None
    assert N.parse_count_size("25MPa") is None


@pytest.mark.parametrize(
    "text, size, mm",
    [
        ('LIG.: 10M@6" c/c', "10M", 152.4),
        ("LIG.: 15M@8'' c/c", "15M", 203.2),
        ("H.:15M@200mm c/c", "15M", 200.0),
        ("10M @ 4”", "10M", 101.6),
    ],
)
def test_size_spacing(text, size, mm):
    assert N.parse_size_spacing(text) == N.SizeSpacing(size, mm)


def test_section_and_feet_inches():
    assert N.parse_section('COL. 18"x20"') == (457.2, 508.0)
    assert N.parse_feet_inches("143' - 3\"") == pytest.approx(143 * 304.8 + 3 * 25.4)
    assert N.parse_feet_inches("90' - 0\"") == pytest.approx(27432.0)
    assert N.parse_feet_inches("no numbers") is None


def test_shop_vert_and_ties():
    assert N.parse_shop_vert("VERT: 4 25M B7-01") == N.ShopVert(4, "25M", "B7-01")
    t = N.parse_shop_ties('ÉTRI: 25 10M T4X21 @6"')
    assert t == N.ShopTies(25, "10M", "T4X21", 152.4)
    assert N.parse_shop_ties("ÉTRI: 6 10M T4X21").spacing_mm is None
    assert N.parse_shop_vert("VERTICALES") is None


def test_grid_label_and_levels():
    assert N.parse_grid_label("J-12") == ("J", 12.0)
    assert N.parse_grid_label("A-7.5") == ("A", 7.5)
    assert N.parse_grid_label("C-01") is None  # element mark, not a grid cell
    assert N.canon_level("NIVEAU 4") == "N4"
    assert N.canon_level("REZ-DE-CHAUSSÉE") == "RDC"
    assert N.canon_level("SOUS-SOL") == "SS"
    assert N.canon_level("TOIT APPENTIS") == "TOIT_APP"
    assert N.canon_level("TOIT") == "TOIT"
    assert N.canon_level("ECHELLE") is None
    assert N.plan_column_level("PLAN DES COLONNES - NIVEAU 4  ECH: 1/8") == "N4"
    assert N.plan_column_level("PLAN DES COLONNES - SOUS-SOL - A") == "SS"
    assert N.plan_column_level("PLAN DES POUTRES") is None


def test_shop_notation_tolerates_what_ocr_does_to_it():
    # OCR often drops spaces and the quote mark; the mark must not swallow the spacing
    t = N.parse_shop_ties("ETRI:1310MT4X18@9")
    assert t == N.ShopTies(13, "10M", "T4X18", 228.6)
    v = N.parse_shop_vert("VERT:425MB7-01")
    assert v == N.ShopVert(4, "25M", "B7-01")
    assert N.parse_shop_ties('ETRI:510M T4X21@6"').spacing_mm == 152.4


def test_level_names_tolerate_dropped_spaces_from_ocr():
    assert N.canon_level("NIVEAU4") == "N4" and N.canon_level("LEVEL12") == "N12"
    assert N.plan_column_level("PLAN DES COLONNES - NIVEAU2") == "N2"


def test_grid_rows_may_be_fractional_like_columns():
    assert N.parse_grid_label("J.5-12") == ("J.5", 12.0)
    assert N.parse_grid_label("A.5-7.5") == ("A.5", 7.5)
    assert N.parse_grid_label("C.5-01") is None  # still a mark, not a cell


def test_schedule_title_gives_the_lower_level_of_the_span():
    assert N.schedule_level("COLUMNS LEVEL3@LEVEL4 PART 1") == "N3"
    assert N.schedule_level("COLUMNS-LEVEL-11@Roof") == "N11"
    assert N.schedule_level("COLUMNS LEVEL-FDN@SS1") == "FDN"
    assert N.schedule_level("COLUMNS LEVEL-SS1@GROUND") == "SS"
    assert N.schedule_level("COLUMNS LEVEL-GROUND@2") == "RDC"
    assert N.schedule_level("COLUMNSLEVEL2@LEVEL3") == "N2"  # OCR dropped the spaces
    assert N.schedule_level("PLAN DES COLONNES - NIVEAU 4") is None


def test_grid_rows_may_carry_a_prime():
    assert N.parse_grid_label("F'-34") == ("F'", 34.0)
    assert N.parse_grid_label("B.1-35.1") == ("B.1", 35.1)


def test_schedule_bar_specs_survive_glued_ocr_text():
    spec = N.parse_schedule_specs("5x425M25Y1800A 2x4 30M 30Y2100,")
    assert [(s.mult, s.count, s.size, s.mark) for s in spec] == [
        (5, 4, "25M", "25Y1800A"),
        (2, 4, "30M", "30Y2100"),
    ]
    ties = N.parse_schedule_specs('5x18 10M 10Q4400 @150 3x18 10M10Q4400 @6"')
    assert [(s.mult, s.count, s.size, s.mark, s.spacing_mm) for s in ties] == [
        (5, 18, "10M", "10Q4400", 150.0),
        (3, 18, "10M", "10Q4400", 152.4),
    ]
    single = N.parse_schedule_specs("4 25M 25Y1800A")
    assert single[0].mult is None and single[0].count == 4
    assert N.parse_schedule_specs("450 x 600") == []


def test_a_spacing_is_not_extended_by_the_next_columns_count():
    # neighbouring columns touch, so OCR prints `@200` and the next `4x16` as `@2004x16`
    ties = N.parse_schedule_specs("3x28 10M 10Q4400 @2004x16 10M 10Q4400 @200")
    assert [(s.mult, s.count, s.spacing_mm) for s in ties] == [(3, 28, 200.0), (4, 16, 200.0)]
    assert N.parse_schedule_specs("2x15 10M 10Q4400 @152.4")[0].spacing_mm == 152.4


def test_schedule_level_without_a_numbered_prefix():
    assert N.schedule_level("COLUMNS FDN@SS1 PART 2") == "FDN"
    assert N.schedule_level("COLONNE SS1@RDC") == "SS"
    assert N.schedule_level("EMAIL ME@HOME") is None  # not level names


def test_schedule_specs_accept_dots_where_ocr_lost_the_spaces():
    specs = N.parse_schedule_specs("5x4.25M.2578111 25Y1800.")
    assert [(s.mult, s.count, s.size) for s in specs] == [(5, 4, "25M")]
    assert specs[0].mark == "2578111"
    ties = N.parse_schedule_specs("3x7 10M.10Q4400 @400")
    assert [(s.mult, s.count, s.size, s.spacing_mm) for s in ties] == [(3, 7, "10M", 400.0)]
    assert N.parse_schedule_specs("scale 2.5 note") == []
    assert N.parse_schedule_specs("12.25M 25Y1800")[0].count == 12  # not split mid-number


def test_several_basements_keep_their_number():
    assert N.canon_level("SOUS-SOL") == "SS" and N.canon_level("SS1") == "SS"
    assert N.canon_level("SOUS-SOL 1") == "SS"  # the first basement is plain SS
    assert N.canon_level("SS2") == "SS2" and N.canon_level("SOUS-SOL 2") == "SS2"
    assert N.canon_level("BASEMENT 3") == "SS3"
    assert N.schedule_level("COLUMNS SS2@SS1") == "SS2"
    assert N.schedule_level("COLUMNS SS1@RDC") == "SS"


def test_a_bare_metric_spacing_is_never_read_as_inches():
    assert N.parse_size_spacing("10M@150").spacing_mm == 150.0
    assert N.parse_shop_ties("ÉTRI: 6 10M T4X21 @150").spacing_mm == 150.0
    assert N.parse_size_spacing("10M@6").spacing_mm == 152.4  # small bare numbers stay inches
    assert N.parse_size_spacing('10M@150"').spacing_mm == 3810.0  # an explicit mark wins


def test_plan_title_accepts_dashes_and_either_order():
    assert N.plan_column_level("COLUMN PLAN – LEVEL 2") == "N2"
    assert N.plan_column_level("COLUMN PLAN — LEVEL 2") == "N2"
    assert N.plan_column_level("COLUMN PLAN: LEVEL 2") == "N2"
    assert N.plan_column_level("LEVEL 3 COLUMN PLAN") == "N3"
    assert N.plan_column_level("ROOF - COLUMN PLAN") == "TOIT"


def test_section_reads_every_configured_section_word():
    assert N.parse_section('COLUMN 18"x20"') == (457.2, 508.0)
    import dataclasses

    es = dataclasses.replace(N.DEFAULT_CONFIG, section_line=("COLUMNA ",))
    assert N.parse_section('COLUMNA 18"x20"', es) == (457.2, 508.0)
    assert N.parse_section('COL. 18"x20"', es) is None  # no longer a section word
