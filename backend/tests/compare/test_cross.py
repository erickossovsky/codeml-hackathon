from l2c.compare.cross import compare_pair, finding_id
from l2c.match.matcher import Pair
from l2c.mock.elements import make_element

PLAN_LEVELS = {"N2"}
SHOP_LEVELS = {"N2"}


def plan(**kw):
    return make_element("plan", "N2", "K", 3, **kw)


def shop(**kw):
    return make_element("shop", "N2", "K", 3, **kw)


def test_field_diffs_are_listed_with_plan_and_shop_values():
    f = compare_pair(
        Pair(plan(count=4), shop(count=6, spacing_mm=304.8), "key"), PLAN_LEVELS, SHOP_LEVELS
    )
    assert f.status == "non_compliant"
    assert {(d.field, d.plan, d.shop) for d in f.diffs} == {
        ("count", 4, 6),
        ("spacing_mm", 152.4, 304.8),
    }
    assert f.plan_ref.element_id and f.shop_ref.element_id and f.evidence.rule.fired


def test_a_missing_or_added_element_needs_trust_and_coverage():
    missing = compare_pair(Pair(plan(), None, "none"), PLAN_LEVELS, SHOP_LEVELS)
    assert missing.status == "missing" and missing.shop_ref is None
    not_covered = compare_pair(Pair(plan(), None, "none"), PLAN_LEVELS, {"N9"})
    assert not_covered.status == "needs_review" and "no shop data" in not_covered.notes
    added = compare_pair(Pair(None, shop(), "none"), PLAN_LEVELS, SHOP_LEVELS)
    assert added.status == "added" and added.plan_ref is None
    weak = compare_pair(Pair(None, shop(overall=0.3), "none"), PLAN_LEVELS, SHOP_LEVELS)
    assert weak.status == "needs_review"


def test_unbound_blocks_are_never_called_missing():
    f = compare_pair(
        Pair(make_element("plan", "N2", None, None), None, "unbound"), PLAN_LEVELS, SHOP_LEVELS
    )
    assert f.status == "needs_review" and f.evidence.rule.kind == "unbound_plan_block"


def test_finding_ids_are_stable_and_distinguish_the_pair():
    assert finding_id("a", "p1", "s1") == finding_id("a", "p1", "s1")
    assert finding_id("a", "p1", "s1") != finding_id("a", "p1", "s2")
    assert finding_id("a", None, "s1").startswith("F-")
