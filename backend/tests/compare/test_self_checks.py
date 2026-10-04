from l2c.compare.self_checks import (
    internal_consistency_findings,
    learned_band,
    peer_outliers,
    plausibility_findings,
    storey_heights,
)
from l2c.contract import constants as C
from l2c.contract.models import LevelInfo
from l2c.mock.elements import make_element

LEVELS = [
    LevelInfo(level="N2", name="N2", elevation_mm=0.0),
    LevelInfo(level="N3", name="N3", elevation_mm=3500.0),
]


def plan_row(n, **odd):
    return [
        make_element("plan", "N2", "K", c, x=100.0 + c, **(odd if c == 3 else {}))
        for c in range(1, n + 1)
    ]


def test_a_rare_value_among_agreeing_peers_is_an_outlier_with_a_high_score():
    out = peer_outliers(plan_row(12, size="35M"))
    assert [(o.field, o.value, o.mode) for o in out] == [("size", "35M", "25M")]
    assert out[0].score > 0.8 and out[0].element.grid == "K-3"


def test_no_outlier_when_peers_disagree_or_the_group_is_small():
    mixed = [
        make_element("plan", "N2", "K", c, size="25M" if c % 2 else "35M") for c in range(1, 13)
    ]
    assert peer_outliers(mixed) == []
    assert peer_outliers(plan_row(C.PEER_MIN_GROUP - 1, size="35M")) == []


def test_groups_are_per_sheet_and_level():
    elements = plan_row(12) + [make_element("plan", "N3", "K", c, size="35M") for c in range(1, 13)]
    assert peer_outliers(elements) == []  # N3 is uniformly 35M, N2 uniformly 25M


def test_storey_heights_come_from_consecutive_levels():
    assert storey_heights(LEVELS) == {"N2": 3500.0}


def test_learned_band_adapts_to_the_projects_own_data_and_falls_back_when_small():
    assert learned_band([1.0] * 5)[2] == "fallback"
    lo, hi, how = learned_band([1.0] * 30)
    assert how == "learned" and lo < 1.0 < hi
    lo2, hi2, _ = learned_band([1.6] * 30)  # a project that is consistently different
    assert lo2 < 1.6 < hi2


def test_internal_consistency_flags_an_impossible_tie_count_only():
    ok = [make_element("shop", "N2", "K", c, tie_count=23, x=100.0 + c) for c in range(1, 25)]
    bad = make_element("shop", "N2", "L", 1, tie_count=60)
    out = internal_consistency_findings([*ok, bad], LEVELS)
    assert [f.grid for f in out] == ["L-1"] and out[0].status == "needs_review"
    assert internal_consistency_findings(ok, []) == []  # no elevations: nothing to check


def test_plausibility_reports_failed_extraction_checks():
    e = make_element("plan", "N2", "K", 3)
    bad = e.model_copy(
        update={
            "quality": e.quality.model_copy(update={"consistency_failed": ["size_in_vocabulary"]})
        }
    )
    out = plausibility_findings([e, bad])
    assert len(out) == 1 and "size_in_vocabulary" in out[0].notes
