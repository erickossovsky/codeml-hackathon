"""Rule-level tests of the new pipeline with a fake LLM (no model needed)."""

from l2c.free.facts import parse_line
from l2c.llm.client import FakeClient
from l2c.pipeline.assign import assign, build_entities
from l2c.pipeline.compare import build_findings, compare_elements


def _el(id_, source, cell, level, kind="column", bars=None, chars=None, **loc):
    locations = [{"type": "grid", "cell": cell}] if cell else []
    if "cells" in loc:
        locations = [{"type": "grid_cells", "cells": loc["cells"]}]
    locations.append({"type": "level", "value": level, **({"to": loc["to"]} if "to" in loc else {})})
    return {
        "id": id_,
        "source": source,
        "file": f"{source}.pdf",
        "page": 1,
        "x": 1.0,
        "y": 2.0,
        "kind": kind,
        "name": cell,
        "locations": locations,
        "bars": bars or [],
        "characteristics": chars or [],
        "descriptions": [],
        "match": {},
        "quality": {"has_facts": True},
    }


def test_facts_cover_notations_without_fixed_labels():
    assert parse_line("ARM.: 4-25M")["bars"][0]["count"] == 4
    tie = parse_line("LIG.: 10M@6\" c/c")["bars"][0]
    assert tie["spacing_mm"] == 152.4 and tie["size"] == "10M"
    assert parse_line("22(18)-20M")["bars"][0]["secondary_count"] == 18
    assert parse_line("3x4 20M 20Z3150.")["bars"][0]["groups"] == 3
    assert parse_line("COL. 16\"x24\"")["characteristics"][0]["value_mm"] == [406.4, 609.6]


def test_multiplier_is_not_a_section():
    assert parse_line("3x4")["characteristics"] == []


def test_implausible_count_is_dropped():
    bar = parse_line("620 20M.2023150 20Z3150.")["bars"][0]
    assert "count" not in bar and bar["count_suspect"] == 620


def test_equal_after_unit_normalisation_is_a_check_not_a_flag():
    plan = _el("p", "plan", "B-3", "N2", bars=[{"size": "10M", "spacing_mm": 152.4, "source_text": "10M@6\""}])
    shop = _el("s", "shop", "B-3", "N2", bars=[{"size": "10M", "spacing_mm": 150.0, "source_text": "10M @150"}])
    out = compare_elements(plan, shop, FakeClient(), {"calls": 0})
    assert not out["flags"] and any(c["property"] == "spaced bars spacing mm" for c in out["checks"])


def test_bar_size_change_is_one_difference_not_two_missing_groups():
    plan = _el("p", "plan", "D-2", "N2", bars=[{"count": 6, "size": "25M"}])
    shop = _el("s", "shop", "D-2", "N2", bars=[{"count": 6, "size": "20M"}])
    out = compare_elements(plan, shop, FakeClient(), {"calls": 0})
    assert [f["property"] for f in out["flags"]] == ["counted bars size"]
    assert any(c["property"] == "counted bars count" for c in out["checks"])


def test_assignment_prefers_exact_cell_and_leaves_extras_unmatched():
    plan = [
        _el("p1", "plan", "B-3", "N2", chars=[{"name": "section", "value_mm": [400, 500]}]),
        _el("p2", "plan", "B-4", "N2"),
    ]
    shop = [_el("s1", "shop", None, "N2", cells=["B-3"], to="N3", chars=[{"name": "section", "value_mm": [400, 500]}])]
    res = assign(plan, shop, FakeClient(rule=lambda u: "no"))
    pairs = {p["plan_elements"][0]: p["shop_cell"] for p in res.pairs}
    assert pairs == {"p1": "B-3"}  # the neighbour B-4 is not forced onto the slot
    assert len(res.plan_unmatched) == 1


def test_unmatched_elements_are_listed_as_info_not_discrepancies():
    plan = [_el("p1", "plan", "A-1", "N5")]
    shop = [_el("s1", "shop", "Z-9", "N2")]
    client = FakeClient(rule=lambda u: "no")
    res = assign(plan, shop, client)
    findings = build_findings(plan, shop, res, client)
    assert findings["counts"] == {"not_in_shop": 1, "not_in_plan": 1}
    assert all(r["flags"] == [] and r["severity"] == "info" for r in findings["entities"])


def test_duplicate_plan_elements_form_one_entity():
    plan = [_el("p1", "plan", "B-3", "N2"), _el("p2", "plan", "B-3", "N2")]
    ents = build_entities(plan)
    assert len(ents) == 1 and len(ents[0].members) == 2


def test_llm_prompts_stay_small():
    from l2c.llm import prompts as P

    for system in (P.LINK_SYSTEM, P.MATCH_SYSTEM, P.PROPERTY_SYSTEM):
        assert len(system) // 3 < 300  # a few hundred tokens at most, before the one-element question
