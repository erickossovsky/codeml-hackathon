from collections import Counter

from l2c.mock.generate import mock_project


def test_mock_project_shape_is_stable():
    m = mock_project()
    plan = [e for e in m.bundle.elements if e.source == "plan"]
    shop = [e for e in m.bundle.elements if e.source == "shop"]
    assert len(plan) == 24 + 1  # 2 levels x 2 rows x 6 cols, plus one unbound block
    assert len(shop) == 24 - 1 + 1 + 1 + 1 + 1  # one missing, plus added, two duplicates, FDN
    assert len({e.id for e in m.bundle.elements}) == len(m.bundle.elements)
    assert Counter(x.check_type for x in m.expected)["cross.plan_vs_shop"] == 8


def test_mock_defects_are_visible_in_the_data():
    m = mock_project()
    by = {(e.source, e.level, e.grid): e for e in m.bundle.elements if e.grid}
    assert by[("shop", "N2", "K-4")].armature[0].quantite == 6
    assert by[("plan", "N2", "K-5")].armature[0].diametre == "35M"
    assert ("shop", "N2", "L-8") not in by
    assert by[("shop", "N3", "L-5")].armature[1].espacement_mm == 304.8
