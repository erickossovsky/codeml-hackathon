"""The UI's view of the findings and of the streaming run's progress (synthetic values only)."""

from l2c.pipeline.envelope import run_result


def _rec(i, status, flags=(), info=(), group=None, kind="column"):
    member = {
        "element_id": f"e{i}",
        "file": "a/plan.pdf",
        "sheet": "S-1",
        "page": 1,
        "x": 10.0,
        "y": 20.0,
    }
    rec = {
        "entity_id": f"F-{i:05d}",
        "kind": kind,
        "level": "N2",
        "location": {"grid": "B-3"},
        "members": {"plan": [member], "shop": [{**member, "file": "DA/shop.pdf"}]},
        "status": status,
        "checks": [],
        "flags": list(flags),
        "info": list(info),
        "match": {},
        "notes": "",
    }
    if group:
        rec["group"] = group
    return rec


def test_run_result_counts_every_record_and_lists_what_to_look_at():
    flag = {"property": "counted bars count", "plan": 6, "shop": 4, "result": "different"}
    maybe = {
        "property": "counted bars size",
        "plan": "20M",
        "shop": "15M",
        "result": "possible_difference",
    }
    findings = {
        "entities": [
            _rec(1, "differs", flags=[flag]),
            _rec(2, "uncertain", info=[maybe]),
            _rec(3, "uncertain", info=[{**maybe, "group": "G1"}], group="G1"),
            _rec(4, "conforms"),
            _rec(5, "not_in_shop", kind="railing"),
        ],
        "systematic": [
            {
                "group": "G1",
                "property": "counted bars size",
                "relation": "plan 20M, shop 15M",
                "count": 3,
                "places": [{"grid": "B-3", "level": "N2", "kind": "slab", "plan": None}],
            }
        ],
    }
    r = run_result(findings, "run1", "p", ["plan.pdf"], ["shop.pdf"])
    assert r["counts"] == {
        "compliant": 1,
        "non_compliant": 1,
        "missing": 1,
        "added": 0,
        "needs_review": 2,
    }
    assert [(f["id"], f["status"]) for f in r["findings"]] == [
        ("F-00001", "non_compliant"),
        ("F-00002", "needs_review"),
        ("G1", "needs_review"),
    ]
    first = r["findings"][0]
    assert first["diffs"] == [{"field": "counted bars count", "plan": 6, "shop": 4, "delta": -2.0}]
    assert first["type_element"] == "colonne" and first["plan_ref"]["fichier"] == "plan.pdf"


def test_progress_becomes_ui_steps_that_open_once_and_close_once():
    from l2c.api import _translate

    prog = {
        "files": [
            {"file": "plan.pdf", "source": "plan", "status": "read", "elements": 12},
            {"file": "DA/a.pdf", "source": "shop", "status": "waiting"},
        ]
    }
    seen = {"ingest"}
    out = _translate(
        {"step": "extract_plan", "status": "file", "detail": "plan.pdf: 12 elements (1/2 files)"},
        prog,
        seen,
    )
    kinds = [(e["kind"], e.get("step"), e.get("status")) for e in out]
    assert kinds == [
        ("step", "extract_plan", "active"),
        ("note", "extract_plan", None),
        ("step", "extract_plan", "done"),
        ("step", "extract_shop", "active"),
    ]
    assert out[2]["detail"] == "12 elements"
    again = _translate({"step": "ocr", "status": "active", "detail": "3 pages"}, prog, seen)
    assert [e["kind"] for e in again] == ["note"]  # extract_shop is already open
