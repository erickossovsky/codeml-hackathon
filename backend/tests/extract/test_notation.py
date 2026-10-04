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
