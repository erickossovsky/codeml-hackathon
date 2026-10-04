from l2c.extract import quality as Q


def test_attr_penalties_stack():
    assert Q.attr(4).conf == 1.0
    assert Q.attr(4, text_source="ocr", ocr_conf=0.9, snapped=True).conf == round(0.9 * 0.9, 3)
    assert Q.attr(7, status="derived").conf == 0.8


def test_overall_is_the_weakest_link_times_consistency():
    loc = Q.location("outline", 1.0, margin=1.0, grid_cell="D-6", binding_method="hungarian")
    attrs = {"count": Q.attr(4), "size": Q.attr("25M"), "spacing": Q.attr(152.4, conf=0.8)}
    q = Q.build_quality(
        type_conf=1.0, level_conf=1.0, loc=loc, attrs=attrs, passed=["a"], failed=[], flags=["x"]
    )
    assert q.overall == 0.8
    q2 = Q.build_quality(
        type_conf=1.0, level_conf=1.0, loc=loc, attrs=attrs, passed=[], failed=["b", "c"], flags=[]
    )
    assert q2.overall == round(0.8 * 0.85**2, 3)


def test_location_score_reflects_anchor_and_margin():
    strong = Q.location("outline", 1.0, margin=1.0)
    weak = Q.location("text_only", 0.62, margin=0.1)
    assert Q.location_score(strong) == 1.0
    assert Q.location_score(weak) < 0.3


def test_column_checks():
    passed, failed = Q.column_checks(4, "25M", 152.4)
    assert passed == ["size_in_vocabulary", "count_plausible", "spacing_plausible"]
    assert failed == []
    _, failed = Q.column_checks(0, "26M", 5.0)
    assert set(failed) == {"count_plausible", "size_in_vocabulary", "spacing_plausible"}
