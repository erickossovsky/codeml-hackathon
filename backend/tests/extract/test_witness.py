from l2c.contract.io import MetaBundle
from l2c.contract.models import Armature, ElementExt, MatchKey
from l2c.extract import quality as Q
from l2c.extract.witness import witness


def make_element(source, level, row, col, *, count=4, x=0.0):
    """A minimal synthetic element: only the fields the witness reads matter."""
    grid = f"{row}-{col:g}"
    return ElementExt(
        id=f"{source}_{level}_{grid}",
        source=source,
        fichier=f"{source}.pdf",
        feuillet=None,
        page=1,
        x=x,
        y=0.0,
        type_element="colonne",
        element=grid,
        armature=[Armature(repere="V", diametre="25M", quantite=count)],
        match_key=MatchKey(type="colonne", level=level, row=row, col=col),
        grid=grid,
        level=level,
        bbox=(x, 0.0, x + 1, 1.0),
        quality=Q.build_quality(
            type_conf=1.0,
            level_conf=1.0,
            loc=Q.location("outline", 1.0),
            attrs={},
            passed=[],
            failed=[],
            flags=[],
        ),
        extraction_method="rules",
    )


def project(shuffle_atypical: bool):
    cols = range(1, 21)
    odd = {3: 6, 9: 8, 15: 10}  # three atypical plan columns (different bar count)
    plan = [make_element("plan", "N2", "K", c, count=odd.get(c, 4), x=10.0 * c) for c in cols]
    shop_counts = dict(odd)
    if shuffle_atypical:  # the shop has the unusual values, but in other cells
        shop_counts = {4: 6, 10: 8, 16: 10}
    shop = [
        make_element("shop", "N2", "K", c, count=shop_counts.get(c, 4), x=10.0 * c) for c in cols
    ]
    return MetaBundle(project="w", elements=plan + shop)


def test_correct_binding_makes_atypical_columns_agree_with_the_shop():
    w = witness(project(shuffle_atypical=False))
    assert w.atypical_total == 3 and w.atypical_agree == 3 and w.binding_accuracy == 1.0
    assert w.typical_total == 17 and w.typical_agree == 17
    assert w.matched_cells == 20


def test_wrong_binding_drops_atypical_agreement_to_chance():
    w = witness(project(shuffle_atypical=True))
    assert w.atypical_agree == 0 and w.binding_accuracy == 0.0
    assert w.chance is not None and w.chance < 0.5


def test_no_atypical_columns_means_no_estimate():
    plan = [make_element("plan", "N2", "K", c) for c in range(1, 6)]
    shop = [make_element("shop", "N2", "K", c) for c in range(1, 6)]
    w = witness(MetaBundle(project="x", elements=plan + shop))
    assert w.binding_accuracy is None and w.atypical_total == 0
