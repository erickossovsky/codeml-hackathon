"""S4: compare matched pairs and write the findings.

Code normalises units and aligns properties first. Properties that line up by name or by shape
(counted bars, spaced bars, section, strength) are compared by rule on normalised values, so a
value written in inches and the same value in millimetres is a check, never a flag. The LLM sees
one leftover plan property and one leftover shop property at a time and says whether they are the
same property and whether they agree; a code check then overrides it if the normalised numbers say
otherwise.

Findings are one record per real-world element, listing its plan and shop members with checks,
flags and info lines. Every plan and shop element with data lands in some record.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from l2c.llm import prompts as P
from l2c.llm.client import LlmClient, choose_many
from l2c.pipeline.assign import Result, _loc, same_length

SECTION_TOL_MM = 1.0
MAX_LLM_CALLS = 120
AGREE_WEIGHT = {
    "spacing_mm": 2,
    "secondary_count": 2,
    "count": 1,
    "size": 1,
}  # distinctive values weigh more
NOT_PAIRED = 1e3


def _bar_layout(b: dict) -> str:
    return "spaced" if b.get("spacing_mm") is not None else "counted"


def _total_count(b: dict) -> int | None:
    """Bars per element. A shop list line such as `3x4 25M` covers three identical columns of four
    bars each (it agrees with the `3 REQUIS` and the three grid cells listed), so the multiplier is
    not part of the count of one element."""
    return b.get("count")


def _bar_text(b: dict) -> str:
    parts = []
    if b.get("count") is not None:
        g = f"{b['groups']} x " if b.get("groups") else ""
        parts.append(f"{g}{b['count']}")
    if b.get("secondary_count") is not None:
        parts.append(f"({b['secondary_count']})")
    if b.get("size"):
        parts.append(b["size"])
    if b.get("spacing_mm") is not None:
        parts.append(f"@ {b['spacing_mm']:g} mm")
    if b.get("mark"):
        parts.append(f"mark {b['mark']}")
    return " ".join(parts) or b.get("source_text", "?")


def _agreement(p: dict, s: dict) -> float | None:
    """How much two bar statements say the same thing; None when they cannot be one bar group (a
    counted group and a spaced one, a dowel line and a tie line)."""
    if _bar_layout(p) != _bar_layout(s):
        return None
    if p.get("role_hint") and s.get("role_hint") and p["role_hint"] != s["role_hint"]:
        return None  # a dowel line is not a tie line
    if (p.get("role_hint") == "dowel") != (s.get("role_hint") == "dowel"):
        return None
    score = 0.01  # compatible: worth pairing when nothing better is on offer
    if p.get("role_hint") and p.get("role_hint") == s.get("role_hint"):
        score += 1
    for k, w in AGREE_WEIGHT.items():
        a, b = p.get(k), s.get(k)
        if a is None or b is None:
            continue
        score += w if (same_length(a, b) if k == "spacing_mm" else a == b) else 0
    return score


def _pair_bars(plan: list[dict], shop: list[dict]):
    """One-to-one alignment of plan and shop bar groups that maximises what agrees. The same group with
    one number changed still agrees on its other values (a spacing, a secondary count, a count, a size),
    so it wins over another group that happens to share one of them."""
    n, m = len(plan), len(shop)
    if not n or not m:
        return [], list(range(n)), list(range(m))
    cost = np.zeros((n + m, m + n))  # dummy rows and columns: a group may stay unpaired
    cost[:n, :m] = NOT_PAIRED
    for i, p in enumerate(plan):
        for j, s in enumerate(shop):
            a = _agreement(p, s)
            if a is not None:
                cost[i, j] = -a
    pairs = [
        (int(i), int(j))
        for i, j in zip(*linear_sum_assignment(cost), strict=True)
        if i < n and j < m and cost[i, j] < 0
    ]
    used_p, used_s = {i for i, _ in pairs}, {j for _, j in pairs}
    return (
        sorted(pairs),
        [i for i in range(n) if i not in used_p],
        [j for j in range(m) if j not in used_s],
    )


def _record(prop: str, plan: Any, shop: Any, relation: str, by: str, **extra: Any) -> dict:
    return {"property": prop, "plan": plan, "shop": shop, "result": relation, "by": by, **extra}


def _bar_records(p: dict, s: dict, checks: list, flags: list, info: list) -> None:
    """Compare one plan bar group with one shop bar group, field by field. A difference carries the
    place of the shop note it was read from (`shop_ref`) when the bar knows it."""
    base = f"{_bar_layout(p)} bars"
    texts = {"plan_text": p.get("source_text"), "shop_text": s.get("source_text")}
    where = {"shop_ref": s["_ref"]} if s.get("_ref") else {}
    fields = []
    pc, sc = _total_count(p), _total_count(s)
    if (p.get("secondary_count") is None) != (s.get("secondary_count") is None):
        info.append(_record(base, _bar_text(p), _bar_text(s), "not_comparable", "rule", **texts))
        return
    if (
        p.get("size")
        and s.get("size")
        and p["size"] != s["size"]
        and pc is not None
        and sc is not None
        and pc != sc
    ):
        # different size and different count: two different bar groups, not one group that changed
        info.append(_record(base, _bar_text(p), _bar_text(s), "not_comparable", "rule", **texts))
        return
    if pc is not None and sc is not None:
        fields.append(("count", pc, sc, pc == sc))
    if p.get("secondary_count") is not None and s.get("secondary_count") is not None:
        fields.append(
            (
                "secondary count",
                p["secondary_count"],
                s["secondary_count"],
                p["secondary_count"] == s["secondary_count"],
            )
        )
    if p.get("size") and s.get("size"):
        fields.append(("size", p["size"], s["size"], p["size"] == s["size"]))
    if p.get("spacing_mm") is not None and s.get("spacing_mm") is not None:
        fields.append(
            (
                "spacing mm",
                p["spacing_mm"],
                s["spacing_mm"],
                same_length(p["spacing_mm"], s["spacing_mm"]),
            )
        )
    if not fields or not any(f[3] for f in fields):
        # nothing comparable, or nothing in this pair agrees: two different notes, not one note with a changed number
        info.append(_record(base, _bar_text(p), _bar_text(s), "not_comparable", "rule", **texts))
        return
    for name, pv, sv, same in fields:
        if same:
            checks.append(_record(f"{base} {name}", pv, sv, "equal", "rule", **texts))
        else:
            flags.append(_record(f"{base} {name}", pv, sv, "different", "rule", **texts, **where))


def _restates(a: dict, b: dict) -> bool:
    """`a` says what `b` says with at most one word changed, in another note: the same line printed
    again, possibly with one number changed. Two lines of one note are two bar groups (the long and the
    transverse bars of a footing can read the same)."""
    ra, rb = a.get("_ref"), b.get("_ref")
    if not ra or not rb or ra["element_id"] == rb["element_id"]:
        return False
    if _bar_layout(a) != _bar_layout(b) or a.get("role") != b.get("role"):
        return False
    ta, tb = _words(a), _words(b)
    return len(ta) == len(tb) >= 2 and sum(x != y for x, y in zip(ta, tb, strict=True)) <= 1


def _words(b: dict) -> list[str]:
    return [w.strip(".,;:") for w in (b.get("source_text") or "").split()]


def _same_role(a: dict, b: dict) -> bool:
    """Two notes name the same role for their lines (vertical bars, ties, dowels): both describe that
    bar group of the member, so each has to agree with the plan's line."""
    ra, rb = a.get("_ref"), b.get("_ref")
    if not ra or not rb or ra["element_id"] == rb["element_id"]:
        return False
    return (
        bool(a.get("role_hint"))
        and a.get("role_hint") == b.get("role_hint")
        and _bar_layout(a) == _bar_layout(b)
    )


def _client_ask(client: LlmClient, state: dict):
    def ask(label: str, plan_text: str, shop_text: str):
        c = client.choose(
            P.PROPERTY_SYSTEM,
            _property_prompt(label, plan_text, shop_text),
            P.PROPERTY_OPTIONS,
            version=P.PROPERTY_VERSION,
        )
        state["calls"] = state.get("calls", 0) + 1
        return c.option, c.certainty

    return ask


def _property_prompt(label: str, plan_text: str, shop_text: str) -> str:
    return f"PLAN: {label} {plan_text}\nSHOP: {label} {shop_text}\nANSWER:"


def compare_elements(
    plan_el: dict, shop_el: dict, ask, llm_state: dict | None = None
) -> dict[str, list]:
    """`ask(label, plan_text, shop_text)` answers a leftover-property question; a client may be passed
    instead, for single use."""
    if hasattr(ask, "choose"):
        ask = _client_ask(ask, llm_state if llm_state is not None else {})
    checks: list[dict] = []
    flags: list[dict] = []
    info: list[dict] = []
    pbars, sbars = plan_el.get("bars", []), shop_el.get("bars", [])
    pairs, left_p, left_s = _pair_bars(pbars, sbars)
    for i, j in pairs:
        _bar_records(pbars[i], sbars[j], checks, flags, info)
    # a leftover shop line that restates a paired one (the same note printed again, on another sheet or
    # in a bar list), or that another note states for the same named role (the vertical bars, the ties
    # of the member), is a second statement of the same bar group: it is compared with the same plan line
    for j in list(left_s):
        twin = next((i for i, k in pairs if _restates(sbars[j], sbars[k])), None)
        if twin is None:
            twin = next((i for i, k in pairs if _same_role(sbars[j], sbars[k])), None)
        if twin is not None:
            _bar_records(pbars[twin], sbars[j], checks, flags, info)
            left_s.remove(j)
    # leftovers: one plan property and one shop property per question
    for i in left_p:
        placed = False
        for j in left_s:
            ans = ask("vertical or tie bars", _bar_text(pbars[i]), _bar_text(sbars[j]))
            if ans and ans[0] == "same":
                checks.append(
                    _record(
                        "bars",
                        _bar_text(pbars[i]),
                        _bar_text(sbars[j]),
                        "equal",
                        "llm",
                        llm_certainty=ans[1],
                    )
                )
                left_s.remove(j)
                placed = True
                break
            if ans and ans[0] == "different" and _numbers_differ(pbars[i], sbars[j]):
                where = {"shop_ref": sbars[j]["_ref"]} if sbars[j].get("_ref") else {}
                info.append(
                    _record(
                        "bars",
                        _bar_text(pbars[i]),
                        _bar_text(sbars[j]),
                        "possible_difference",
                        "llm",
                        llm_certainty=ans[1],
                        **where,
                    )
                )
                left_s.remove(j)
                placed = True
                break
        if not placed:
            info.append(
                _record(
                    "bars",
                    _bar_text(pbars[i]),
                    None,
                    "plan_only",
                    "rule",
                    plan_text=pbars[i].get("source_text"),
                )
            )
    for j in left_s:
        info.append(
            _record(
                "bars",
                None,
                _bar_text(sbars[j]),
                "shop_only",
                "rule",
                shop_text=sbars[j].get("source_text"),
            )
        )
    # characteristics: aligned by name
    pch = {
        c["name"]: c
        for c in plan_el.get("characteristics", [])
        if c["name"] not in {"symbol_size_pt", "size_pt", "shape"}
    }
    sch = {
        c["name"]: c
        for c in shop_el.get("characteristics", [])
        if c["name"] not in {"symbol_size_pt", "size_pt", "shape", "quantity_required"}
    }
    for name in sorted(set(pch) | set(sch)):
        p, s = pch.get(name), sch.get(name)
        if p and s:
            if "value_mm" in p and "value_mm" in s and isinstance(p["value_mm"], list):
                same = all(
                    same_length(a, b, SECTION_TOL_MM)
                    for a, b in zip(p["value_mm"], s["value_mm"], strict=False)
                )
                pv, sv = p["value_mm"], s["value_mm"]
            elif "value_mm" in p and "value_mm" in s:
                same = same_length(p["value_mm"], s["value_mm"], SECTION_TOL_MM)
                pv, sv = p["value_mm"], s["value_mm"]
            else:
                pv, sv = p["value"], s["value"]
                same = str(pv).strip().lower() == str(sv).strip().lower()
            rec = _record(
                name,
                pv,
                sv,
                "equal" if same else "different",
                "rule",
                plan_text=p.get("source_text"),
                shop_text=s.get("source_text"),
            )
            # outside the reinforcement itself (section, elevation, concrete): evidence for the pairing,
            # listed for the engineer, never a non-conformity on its own
            (checks if same else info).append(rec)
        elif p:
            info.append(
                _record(name, p["value"], None, "plan_only", "rule", plan_text=p.get("source_text"))
            )
        else:
            info.append(
                _record(name, None, s["value"], "shop_only", "rule", shop_text=s.get("source_text"))
            )
    return {"checks": checks, "flags": flags, "info": info}


STRONG = ("secondary count", "spacing mm", "type")  # values specific enough to identify a note


def evidence_weight(checks: list[dict]) -> int:
    """How much the agreeing values say that the two notes are the same element. A bar size or a
    count that agrees is weak (most notes share them); a spacing, a secondary count or a type code
    that agrees is strong; an agreeing section is weak evidence too. The same agreement stated twice
    (two identical bar groups, the same note on two sheets) counts once."""
    w = 0
    seen: set[str] = set()
    for c in checks:
        prop = c["property"]
        key = json.dumps([prop, c.get("plan"), c.get("shop")], default=str)
        if key in seen:
            continue
        seen.add(key)
        if any(k in prop for k in STRONG):
            w += 2
        elif prop.endswith(("count", "size")) or prop == "section":
            w += 1
    return w


def combined(elements: list[dict], refs: bool = False) -> dict:
    """All the statements about one member at one place and level, from several notes: a column strip
    prints its vertical bars and its ties as two notes, a slab cell can carry several bar lines.
    A statement repeated in another note (the same note printed twice) counts once; two identical bar
    groups in one note (the long and the transverse bars of a footing) are two groups. With `refs`,
    each bar carries the place of its note (`_ref`)."""
    bars: list[dict] = []
    kept: Counter = Counter()
    chars: dict[str, dict] = {}
    type_key = None
    for e in elements:
        here: Counter = Counter()
        for b in e.get("bars", []):
            key = (
                b.get("role_hint"),
                b.get("count"),
                b.get("size"),
                b.get("secondary_count"),
                b.get("spacing_mm"),
                b.get("source_text"),
            )
            here[key] += 1
            if here[key] > kept[key]:
                kept[key] = here[key]
                bars.append({**b, "_ref": _ref(e)} if refs else b)
        for c in e.get("characteristics", []):
            chars.setdefault(c["name"], c)
        type_key = type_key or e.get("type_key")
    return {"bars": bars, "characteristics": list(chars.values()), "type_key": type_key}


def identity_score(ent, shop_el: dict, shop_cell: str | None) -> int:
    """How sure the pairing is that the plan and shop elements are one member, from where and what
    they are (not from their values): the same grid cell (2) or a neighbouring cell the plan note sits
    between (1); a shop location written in the shop's own text or strip label (+1); the same known
    kind (+1); the same level (+1)."""
    score = (
        2
        if shop_cell and shop_cell == ent.cell
        else (1 if shop_cell and shop_cell in ent.alts else 0)
    )
    g = _loc(shop_el, "grid") or {}
    if _loc(shop_el, "grid_cells") or g.get("basis") == "strip_label":
        score += 1
    if ent.kind and shop_el.get("kind") and ent.kind == shop_el.get("kind"):
        score += 1
    lv = _loc(shop_el, "level") or {}
    if ent.level and ent.level == lv.get("value"):
        score += 1
    return score


CONFIRM_IDENTITY = (
    4  # pairing evidence needed to call a difference without a distinctive value agreeing
)


def confirm(out: dict, identity: int) -> None:
    """Keep a difference as a non-conformity when the evidence says it is one member with a changed
    value: a distinctive value of the same bar group agrees (a spacing, a secondary count), or the
    agreeing values of the pair weigh 2 or more. Otherwise it becomes a possible difference for review."""
    content = evidence_weight(out["checks"])
    kept, doubtful = [], []
    for fl in out["flags"]:
        same_group = [
            c
            for c in out["checks"]
            if c.get("plan_text") == fl.get("plan_text")
            and c.get("shop_text") == fl.get("shop_text")
        ]
        strong = any(
            any(k in c["property"] for k in ("spacing mm", "secondary count")) for c in same_group
        )
        # measured on planted changes: a pairing threshold cost recall on column ties and did not
        # reduce false alarms, so the agreeing values decide (identity is kept for the report)
        if strong or content >= 2:
            kept.append(fl)
        else:
            doubtful.append({**fl, "result": "possible_difference"})
    out["flags"] = kept
    out["info"].extend(doubtful)


def _numbers_differ(p: dict, s: dict) -> bool:
    """Post-check for an LLM `different`: the normalised numbers must really differ."""
    pc, sc = _total_count(p), _total_count(s)
    if pc is not None and sc is not None and pc != sc:
        return True
    if p.get("size") and s.get("size") and p["size"] != s["size"]:
        return True
    if p.get("spacing_mm") is not None and s.get("spacing_mm") is not None:
        return not same_length(p["spacing_mm"], s["spacing_mm"])
    return False


REPEAT_MIN = 3  # real changes are few and varied; the same change at this many places is a convention or a reading artifact


def _difference_class(fl: dict) -> tuple:
    """What kind of change a difference is: the field and how the two values relate. A count that is
    half or double the other (a total against one layer or one face) is one class whatever the numbers."""
    p, s = fl.get("plan"), fl.get("shop")
    if (
        fl["property"].endswith("count")
        and isinstance(p, (int, float))
        and isinstance(s, (int, float))
        and p
        and s
    ):
        if abs(2 * s - p) <= 1:
            return (fl["property"], "the shop states about half the plan's count")
        if abs(2 * p - s) <= 1:
            return (fl["property"], "the shop states about twice the plan's count")
    return (fl["property"], f"plan {p}, shop {s}")


def group_repeats(records: list[dict]) -> list[dict]:
    """The same difference at REPEAT_MIN places or more becomes one systematic finding for review that
    lists every place. Nothing is dropped: each record keeps the difference as a possible difference
    and points at its group."""
    classes: dict[tuple, dict[int, dict]] = {}
    for r in records:
        for fl in r["flags"]:
            classes.setdefault(_difference_class(fl), {})[id(r)] = r
    groups = []
    for cls, members in classes.items():
        if len(members) < REPEAT_MIN:
            continue
        gid = f"G{len(groups) + 1}"
        places = []
        for r in members.values():
            moved = [
                {**fl, "result": "possible_difference", "group": gid}
                for fl in r["flags"]
                if _difference_class(fl) == cls
            ]
            r["flags"] = [fl for fl in r["flags"] if _difference_class(fl) != cls]
            r["info"].extend(moved)
            r["group"] = gid
            note = f"the same difference is found at {len(members)} places (systematic difference {gid})"
            r["notes"] = f"{r['notes']}; {note}" if r["notes"] else note
            if not r["flags"]:
                r["status"] = "uncertain"
            places.append(
                {
                    "grid": r["location"].get("grid"),
                    "level": r.get("level"),
                    "kind": r.get("kind"),
                    "plan": r["members"]["plan"][0] if r["members"]["plan"] else None,
                }
            )
        groups.append(
            {
                "group": gid,
                "property": cls[0],
                "relation": cls[1],
                "count": len(members),
                "places": places,
            }
        )
    return groups


def _ref(e: dict) -> dict:
    return {
        "element_id": e["id"],
        "file": e["file"],
        "sheet": e.get("sheet"),
        "page": e["page"],
        "x": e["x"],
        "y": e["y"],
    }


def compare_member(plan_el: dict, shop_members: list[dict], ask) -> dict[str, list]:
    """Compare the plan side with everything the shop notes of the member say. Every shop line competes
    for the plan lines (several notes of one cell are usually different bar groups); a line printed
    again elsewhere, possibly changed, is compared too (see `_restates`)."""
    return compare_elements(plan_el, combined(shop_members, refs=True), ask)


def build_findings(plan: list[dict], shop: list[dict], res: Result, client: LlmClient) -> dict:
    by_id = {e["id"]: e for e in plan + shop}
    entities_list = getattr(res, "entities", [])
    entities = {e.id: e for e in entities_list}
    shop_levels = {lv["value"] for e in shop if (lv := _loc(e, "level"))} | {
        lv["to"] for e in shop if (lv := _loc(e, "level")) and lv.get("to")
    }
    # pass 1 only collects the leftover-property questions; they are answered together, in parallel;
    # pass 2 does the comparison with the answers in hand
    wanted: dict[str, tuple[str, str, str]] = {}

    def collect(label: str, plan_text: str, shop_text: str):
        wanted.setdefault(
            _property_prompt(label, plan_text, shop_text), (label, plan_text, shop_text)
        )
        return None

    def sides(pair: dict) -> tuple[dict, dict, list[dict]]:
        ent = entities[pair["plan_entity"]]
        shop_members = [
            by_id[i] for i in pair.get("shop_elements", [pair["shop_element"]]) if i in by_id
        ]
        return combined(ent.members), combined(shop_members), shop_members

    for pair in res.pairs:
        p_side, _, shop_members = sides(pair)
        compare_member(p_side, shop_members, collect)
    prompts = list(wanted)
    got = choose_many(
        client, P.PROPERTY_SYSTEM, prompts, P.PROPERTY_OPTIONS, version=P.PROPERTY_VERSION
    )
    answers = {k: (c.option, c.certainty) for k, c in zip(prompts, got, strict=True)}
    state = {"calls": len(prompts)}

    def answer(label: str, plan_text: str, shop_text: str):
        return answers.get(_property_prompt(label, plan_text, shop_text))

    records: list[dict] = []
    matched_per_shop: dict[str, list[str]] = {}
    for pair in res.pairs:
        matched_per_shop.setdefault(pair["shop_element"], []).append(pair["plan_entity"])
    for n, pair in enumerate(res.pairs, 1):
        ent = entities[pair["plan_entity"]]
        shop_el = by_id[pair["shop_element"]]
        plan_el, shop_side, shop_members = sides(pair)
        out = compare_member(plan_el, shop_members, answer)
        # quantity: how many plan elements the shop line says it covers
        qty = next(
            (
                c["value"]
                for c in shop_el.get("characteristics", [])
                if c["name"] == "quantity_required"
            ),
            None,
        )
        cells = _loc(shop_el, "grid_cells")
        if qty is not None and cells:
            n_matched = len(matched_per_shop[shop_el["id"]])
            if n_matched == len(cells["cells"]):
                rec = _record(
                    "quantity required",
                    n_matched,
                    qty,
                    "equal" if n_matched == qty else "different",
                    "rule",
                )
                (out["checks"] if n_matched == qty else out["flags"]).append(rec)
        pk, sk = plan_el.get("type_key"), shop_side.get("type_key")
        if pk and sk:
            rec = _record("type", pk, sk, "equal" if pk == sk else "different", "rule")
            (out["checks"] if pk == sk else out["flags"]).append(rec)
        identity = identity_score(ent, shop_el, pair["shop_cell"])
        confirm(out, identity)
        possible = any(i.get("result") == "possible_difference" for i in out["info"])
        if out["flags"]:
            status = "differs"
        elif possible:
            status = "uncertain"  # a possible difference: listed for review, not counted as a non-conformity
        else:
            status = "conforms" if out["checks"] else "uncertain"
        notes = ""
        if pair.get("near_cell"):
            notes = "paired through a neighbouring grid cell"
        records.append(
            {
                "kind": ent.kind or shop_el.get("kind"),
                "level": ent.level,
                "location": {"grid": ent.cell, "shop_cell": pair["shop_cell"]},
                "members": {
                    "plan": [_ref(by_id[i]) for i in pair["plan_elements"]],
                    "shop": [_ref(m) for m in shop_members],
                },
                "status": status,
                "checks": out["checks"],
                "flags": out["flags"],
                "info": out["info"],
                "match": {
                    "cost": pair["cost"],
                    "llm_certainty": pair["llm_certainty"],
                    "method": pair["method"],
                    "identity": identity,
                },
                "notes": notes,
                "order": n,
            }
        )
    systematic = group_repeats(records)
    unknown_ids = {entities_list[i].id for i in getattr(res, "level_unknown", set())}
    for ent in res.plan_unmatched:
        if ent.level is None and ent.id in unknown_ids:
            note = "the plan does not state this element's level and the shop drawings cover several levels at this location, so no pairing was guessed"
        elif ent.level and ent.level not in shop_levels:
            note = "no shop drawing data for this level"
        else:
            note = "shop drawings do not cover this element, or no counterpart was found"
        records.append(
            {
                "kind": ent.kind,
                "level": ent.level,
                "location": {"grid": ent.cell},
                "members": {"plan": [_ref(m) for m in ent.members], "shop": []},
                "status": "not_in_shop",
                "checks": [],
                "flags": [],
                "info": [
                    _record("presence", "on plan", "no shop counterpart found", "unmatched", "rule")
                ],
                "severity": "info",
                "match": {},
                "notes": note,
            }
        )
    for e in res.shop_unmatched:
        records.append(
            {
                "kind": e.get("kind"),
                "level": (_loc(e, "level") or {}).get("value"),
                "location": {
                    "grid": (_loc(e, "grid") or {}).get("cell")
                    or ", ".join((_loc(e, "grid_cells") or {}).get("cells", []))
                },
                "members": {"plan": [], "shop": [_ref(e)]},
                "status": "not_in_plan",
                "checks": [],
                "flags": [],
                "info": [
                    _record(
                        "presence",
                        "no plan counterpart found",
                        "in shop drawings",
                        "unmatched",
                        "rule",
                    )
                ],
                "severity": "info",
                "match": {},
                "notes": "shop element with no plan counterpart found",
            }
        )
    for i, r in enumerate(records, 1):
        r["entity_id"] = f"F-{i:05d}"
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "counts": counts,
        "llm_calls": state["calls"],
        "model": getattr(client, "model_id", None),
        "systematic": systematic,
        "entities": records,
    }
