from l2c.match.matcher import match
from l2c.mock.elements import make_element


def plan(row, col, **kw):
    return make_element("plan", "N2", row, col, **kw)


def shop(row, col, **kw):
    return make_element("shop", "N2", row, col, **kw)


def test_exact_key_pairs_and_leftovers():
    pairs = match([plan("K", 3), plan("K", 4)], [shop("K", 3), shop("K", 9)])
    by = {(p.plan.grid if p.plan else None, p.shop.grid if p.shop else None): p for p in pairs}
    assert by[("K-3", "K-3")].method == "key"
    assert ("K-4", None) in by and by[("K-4", None)].method == "none"
    assert (None, "K-9") in by


def test_duplicates_pick_the_best_quality_primary_and_keep_the_rest():
    good = shop("K", 3, fichier="DA/Colonnes/A.pdf", overall=0.95)
    weak = shop("K", 3, fichier="DA/Colonnes/B.pdf", overall=0.5)
    (pair,) = match([plan("K", 3)], [weak, good])
    assert pair.shop is good and pair.extra_shop == [weak]


def test_near_column_fallback_for_fractional_gridlines():
    pairs = match([plan("K", 4)], [shop("K", 3.6)])
    (p,) = pairs
    assert p.method == "near_col" and p.shop.grid == "K-3.6" and p.cost == 0.4


def test_near_fallback_respects_the_distance_limit_and_one_to_one():
    pairs = match([plan("K", 3), plan("K", 3.2)], [shop("K", 3.1)])
    assert sorted(p.method for p in pairs) == ["near_col", "none"]
    far = match([plan("K", 3)], [shop("K", 9)])
    assert sorted(p.method for p in far) == ["none", "none"]


def test_unbound_elements_never_match():
    pairs = match([plan(None, None)], [shop(None, None)])
    assert sorted(p.method for p in pairs) == ["unbound", "unbound"]


def test_duplicate_plan_elements_collapse_to_one_pair_not_a_false_missing():
    good = plan("K", 3, feuillet="S-1", overall=0.95)
    other = plan("K", 3, feuillet="S-2", overall=0.6)
    pairs = match([other, good], [shop("K", 3)])
    assert [p.method for p in pairs] == ["key"]
    assert pairs[0].plan is good and pairs[0].extra_plan == [other]


def test_duplicate_plan_elements_without_a_shop_twin_give_one_missing():
    pairs = match([plan("K", 3, feuillet="S-1"), plan("K", 3, feuillet="S-2")], [])
    assert [p.method for p in pairs] == ["none"] and len(pairs[0].extra_plan) == 1
