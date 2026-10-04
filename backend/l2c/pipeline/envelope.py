"""The findings of the lean pipeline in the shape the UI reads (`RunResult` in
frontend/src/shared/types.ts).

Counts cover every record. The findings list holds what an engineer has to look at: the
non-conformities, the possible ones to verify, and one line per systematic difference (the same
difference at several places). Elements missing from or added in the shop drawings are counted only;
the PDF report lists them.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Any

from l2c.pipeline.report import _review_items, template_sentence

KIND_TO_UI = {
    "footing": "fondation",
    "raft": "fondation",
    "pile": "fondation",
    "pile_cap": "fondation",
    "beam": "poutre",
    "wall": "mur_refend",
    "shear_wall": "mur_refend",
    "column": "colonne",
    "pier": "colonne",
    "slab": "dalle",
}


def _ref(m: dict | None) -> dict | None:
    if not m:
        return None
    return {
        "fichier": PurePath(m["file"]).name,
        "page": m["page"],
        "x": round(float(m["x"]), 1),
        "y": round(float(m["y"]), 1),
    }


def _delta(p: Any, s: Any) -> float | None:
    if isinstance(p, (int, float)) and isinstance(s, (int, float)) and not isinstance(p, bool):
        return round(float(s) - float(p), 2)
    return None


def _value(v: Any) -> Any:
    if isinstance(v, list):
        return " x ".join(f"{x:g}" if isinstance(x, (int, float)) else str(x) for x in v)
    return v


def _finding(rec: dict, status: str) -> dict:
    items = _review_items(rec)
    shop = next((f["shop_ref"] for f in items if f.get("shop_ref")), None) or (
        rec["members"]["shop"][0] if rec["members"]["shop"] else None
    )
    notes = " ".join(template_sentence(f, rec) for f in items[:2])
    if rec.get("notes"):
        notes = f"{notes} ({rec['notes']})" if notes else rec["notes"]
    out = {
        "id": rec["entity_id"],
        "status": status,
        "type_element": KIND_TO_UI.get(rec.get("kind") or "", rec.get("kind") or "element"),
        "grid": rec["location"].get("grid"),
        "level": rec.get("level") or "",
        "check_type": "cross.plan_vs_shop",
        "notes": notes,
        "diffs": [
            {
                "field": f["property"],
                "plan": _value(f["plan"]),
                "shop": _value(f["shop"]),
                "delta": _delta(f["plan"], f["shop"]),
            }
            for f in items
        ],
        "plan_ref": _ref(rec["members"]["plan"][0] if rec["members"]["plan"] else None),
        "shop_ref": _ref(shop),
    }
    if rec.get("match", {}).get("llm_certainty") is not None:
        out["confidence"] = round(rec["match"]["llm_certainty"], 2)
    return {k: v for k, v in out.items() if v is not None}


def run_result(
    findings: dict, run_id: str, project: str, plans: list[str], shops: list[str]
) -> dict:
    counts = {"compliant": 0, "non_compliant": 0, "missing": 0, "added": 0, "needs_review": 0}
    listed: list[dict] = []
    for rec in findings["entities"]:
        st = rec["status"]
        if st == "conforms":
            counts["compliant"] += 1
        elif st == "differs":
            counts["non_compliant"] += 1
            listed.append(_finding(rec, "non_compliant"))
        elif st == "not_in_shop":
            counts["missing"] += 1
        elif st == "not_in_plan":
            counts["added"] += 1
        elif _review_items(rec):
            counts["needs_review"] += 1
            if not rec.get("group"):  # a systematic difference is listed once, below
                listed.append(_finding(rec, "needs_review"))
    for g in findings.get("systematic", []):
        where = ", ".join(f"{p['grid'] or '?'} {p['level'] or ''}".strip() for p in g["places"])
        first = next((p for p in g["places"] if p.get("plan")), None)
        listed.append(
            {
                "id": g["group"],
                "status": "needs_review",
                "type_element": KIND_TO_UI.get(
                    g["places"][0].get("kind") or "", g["places"][0].get("kind") or "element"
                ),
                "grid": f"{g['count']} places",
                "level": "",
                "check_type": "cross.systematic",
                "notes": (
                    f"Same difference at {g['count']} places ({g['relation']}): {where}. "
                    "Usually a drawing convention or a reading artifact; check once."
                ),
                "diffs": [{"field": g["property"], "plan": None, "shop": None, "delta": None}],
                **({"plan_ref": _ref(first["plan"])} if first else {}),
            }
        )
    order = {"non_compliant": 0, "needs_review": 1}
    listed.sort(key=lambda f: (order.get(f["status"], 2), f["id"]))
    return {
        "run_id": run_id,
        "project": project,
        "plan": ", ".join(plans),
        "shop_drawings": shops,
        "counts": counts,
        "findings": listed,
        **({"partial": findings["partial"]} if findings.get("partial") else {}),
    }
