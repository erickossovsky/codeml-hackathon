from l2c.compare.run import run_comparison
from l2c.contract.io import MetaBundle
from l2c.contract.models import Armature
from l2c.mock.elements import make_element


def slab(source, *, groups, col=3):
    return make_element(
        source,
        "N2",
        "K",
        col,
        type_element="dalle",
        armature=[
            Armature(repere=f"B{i}", diametre=d, quantite=c, espacement_mm=s)
            for i, (d, c, s) in enumerate(groups)
        ],
    )


def statuses(plan, shop):
    bundle = MetaBundle(project="x", elements=[*plan, *shop])
    return [
        (f.check_type, f.status, [d.field for d in f.diffs])
        for f in run_comparison(bundle)
        if f.check_type == "cross.plan_vs_shop"
    ]


def test_other_element_types_compare_by_bar_group_not_by_column_layout():
    same = [("15M", 16, None), ("10M", None, 300.0)]
    assert statuses([slab("plan", groups=same)], [slab("shop", groups=same)])[0][1] == "compliant"
    diff = statuses(
        [slab("plan", groups=same)],
        [slab("shop", groups=[("15M", 20, None), ("10M", None, 300.0)])],
    )
    assert diff == [("cross.plan_vs_shop", "non_compliant", ["15M count"])]


def test_missing_and_extra_bar_groups_are_reported():
    out = statuses(
        [slab("plan", groups=[("15M", 16, None), ("20M", 8, None)])],
        [slab("shop", groups=[("15M", 16, None), ("25M", 4, None)])],
    )
    assert out[0][1] == "non_compliant"
    assert sorted(out[0][2]) == ["bar group 20M", "bar group 25M"]


def test_spacing_within_tolerance_is_not_a_difference():
    a = [slab("plan", groups=[("10M", None, 152.4)])]
    b = [slab("shop", groups=[("10M", None, 152.9)])]
    assert statuses(a, b)[0][1] == "compliant"
