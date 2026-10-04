from l2c.extract import notation as N
from l2c.contract.models import Armature
from l2c.extract.generic import collapse_duplicates, extract_generic
from l2c.extract.grid import fit_grid
from l2c.ingest.pages import load_pdf
from tests.extract.pdfmaker import new_doc, put, save


def test_statements_cover_the_forms_seen_on_non_column_sheets():
    s = N.parse_statements('RANG 2: 25M@11" c/c')
    assert [(x.label, x.count, x.size, x.spacing_mm) for x in s] == [("RANG 2", None, "25M", 279.4)]
    s = N.parse_statements("ARM.: 6-30M+GOUJ")
    assert [(x.label, x.count, x.size) for x in s] == [("ARM.", 6, "30M")]
    s = N.parse_statements('10M@9" 10M@12"')
    assert [(x.size, x.spacing_mm) for x in s] == [("10M", 228.6), ("10M", 304.8)]
    assert [(x.count, x.size) for x in N.parse_statements("11-25M")] == [(11, "25M")]
    assert N.parse_statements("TOUT AUTOUR") == []
    assert [x.spacing_mm for x in N.parse_statements("H.:15M@200mm")] == [200.0]


def grid_page(tmp_path, statements):
    doc, page = new_doc(1100, 800)
    for r, y in {"A": 150, "B": 300, "C": 450, "D": 600}.items():
        put(page, 40, y, r)
        put(page, 1000, y, r)
    for c, x in {"1": 150, "2": 400, "3": 650, "4": 900}.items():
        put(page, x, 60, c)
        put(page, x, 740, c)
    for x, y, text in statements:
        put(page, x, y, text)
    return load_pdf(save(doc, tmp_path / "gen.pdf"))[0]


def test_statements_are_bound_to_their_grid_cell_and_merged_into_one_element(tmp_path):
    page = grid_page(
        tmp_path,
        [(155, 155, "11-25M"), (155, 166, '10M@6" c/c'), (405, 305, "8-30M")],
    )
    els = extract_generic(page, "dalle", "N2", fit_grid(page.words), "plan")
    by = {e.grid: e for e in els}
    assert set(by) == {"A-1", "B-2"}
    a = by["A-1"]
    assert a.type_element == "dalle" and a.level == "N2" and a.source == "plan"
    assert {(x.diametre, x.quantite, x.espacement_mm) for x in a.armature} == {
        ("25M", 11, None),
        ("10M", None, 152.4),
    }
    assert a.match_key.key_str() == "dalle|N2|A|1"
    assert a.quality.location.anchor == "text_only"


def test_the_same_statement_listed_twice_is_one_element_with_one_bar_group(tmp_path):
    page = grid_page(tmp_path, [(155, 155, "11-25M"), (170, 175, "11-25M")])
    (e,) = extract_generic(page, "poutre", "N3", fit_grid(page.words), "plan")
    assert len(e.armature) == 1 and e.provenance["occurrences"] == 2


def test_statements_without_a_grid_or_outside_it_stay_unbound_and_flagged(tmp_path):
    doc, page = new_doc(800, 600)
    put(page, 100, 100, "4-25M")
    put(page, 100, 300, '10M@6" c/c')
    (p,) = load_pdf(save(doc, tmp_path / "nogrid.pdf"))
    els = extract_generic(p, "mur_refend", "RDC", None, "plan")
    assert len(els) == 2 and all("unbound_block" in e.quality.flags for e in els)
    assert all(e.match_key.row is None for e in els)
    outside = grid_page(tmp_path, [(980, 780, '15M@6" c/c')])
    (n,) = extract_generic(outside, "dalle", "N2", fit_grid(outside.words), "plan")
    assert "unbound_block" in n.quality.flags


def test_duplicate_elements_in_one_file_collapse_across_pages(tmp_path):
    page = grid_page(tmp_path, [(155, 155, "11-25M")])
    grid = fit_grid(page.words)
    a = extract_generic(page, "dalle", "N2", grid, "plan")
    b = [
        e.model_copy(update={"id": e.id + "_p2", "page": 2})
        for e in extract_generic(page, "dalle", "N2", grid, "plan")
    ]
    merged = collapse_duplicates([*a, *b])
    assert len(merged) == 1 and merged[0].provenance["occurrences"] == 2
    other_file = [e.model_copy(update={"id": e.id + "_x", "fichier": "other.pdf"}) for e in a]
    assert len(collapse_duplicates([*a, *other_file])) == 2  # a second file is not a duplicate


def test_bar_list_statements_are_read_the_way_shop_sheets_print_them():
    s = N.parse_statements("4 25M 25Y1800A")
    assert [(x.count, x.size, x.label, x.spacing_mm) for x in s] == [(4, "25M", "25Y1800A", None)]
    s = N.parse_statements('18 10M 10Q4400 @6"C.F.')
    assert [(x.count, x.size, x.spacing_mm) for x in s] == [(18, "10M", 152.4)]
    # the older forms are unchanged and a dash form is not mistaken for a bar list
    assert [(x.count, x.size) for x in N.parse_statements("11-25M")] == [(11, "25M")]


def test_composite_slab_notation_is_a_count_with_a_secondary_number():
    # the plan prints `16(8)` or `16(8)-25M`; the shop prints `16(8)` alone
    (a,) = N.parse_statements("16(8)")
    assert (a.count, a.secondary, a.size) == (16, 8, None)
    (b,) = N.parse_statements("16(8)-25M")
    assert (b.count, b.secondary, b.size) == (16, 8, "25M")
    assert [(x.count, x.secondary) for x in N.parse_statements("14(8) 18(8)")] == [(14, 8), (18, 8)]
    # a dash form is still a dash form, and `(8)-25M` alone is not a count
    assert [(x.count, x.size) for x in N.parse_statements("11-25M")] == [(11, "25M")]
    assert N.parse_statements("(8)-25M") == []  # no count in front of the bracket


def test_composite_statements_keep_their_count_and_are_not_dropped_in_comparison(tmp_path):
    from l2c.compare.profile import generic_diffs

    page = grid_page(tmp_path, [(155, 155, "16(8)"), (155, 166, "16(8)-25M")])
    (e,) = extract_generic(page, "dalle", "N4", fit_grid(page.words), "plan")
    counts = sorted((a.quantite, str(a.diametre), str(a.repere)) for a in e.armature)
    assert (16, "None", "(8)") in counts and (16, "25M", "(8)") in counts
    shop = e.model_copy(update={"armature": [Armature(repere="(8)", diametre=None, quantite=20)]})
    diffs = generic_diffs(e, shop)
    assert any(d.field == "no size count" or d.field.endswith("count") for d in diffs)
