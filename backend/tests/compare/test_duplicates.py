from l2c.compare.duplicates import duplicate_findings
from l2c.mock.elements import make_element


def shop(file, **kw):
    return make_element("shop", "N2", "K", 3, fichier=file, **kw)


def test_conflicting_values_in_two_shop_files_are_a_cross_file_finding():
    out = duplicate_findings(
        [shop("DA/Colonnes/A.pdf", count=4), shop("DA/Colonnes/B.pdf", count=6)]
    )
    assert [(f.check_type, f.status) for f in out] == [("cross.shop_vs_shop", "needs_review")]
    assert out[0].diffs[0].field == "count"


def test_identical_duplicates_are_harmless():
    assert duplicate_findings([shop("DA/Colonnes/A.pdf"), shop("DA/Colonnes/B.pdf")]) == []


def test_conflict_inside_one_file_is_a_plain_duplicate():
    out = duplicate_findings(
        [shop("DA/Colonnes/A.pdf", count=4, page=1), shop("DA/Colonnes/A.pdf", count=6, page=2)]
    )
    assert [f.check_type for f in out] == ["self.duplicate"]


def test_unbound_elements_and_different_cells_are_ignored():
    a = make_element("shop", "N2", None, None)
    b = make_element("shop", "N2", None, None, x=5.0)
    c = make_element("shop", "N2", "K", 4, fichier="DA/Colonnes/B.pdf")
    assert duplicate_findings([a, b, shop("DA/Colonnes/A.pdf"), c]) == []
