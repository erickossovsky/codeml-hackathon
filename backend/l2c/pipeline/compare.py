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

from typing import Any

from l2c.llm import prompts as P
from l2c.llm.client import LlmClient, choose_many
from l2c.pipeline.assign import Result, _loc, eligible

SPACING_TOL_MM = 5.0
SECTION_TOL_MM = 1.0
MAX_LLM_CALLS = 120


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


def _pair_bars(plan: list[dict], shop: list[dict]):
    """Greedy alignment inside each layout class: same size first, then same spacing or hint."""
    pairs, used_p, used_s = [], set(), set()
    scored = []
    for i, p in enumerate(plan):
        for j, s in enumerate(shop):
            if _bar_layout(p) != _bar_layout(s):
                continue
            if p.get("role_hint") and s.get("role_hint") and p["role_hint"] != s["role_hint"]:
                continue  # a dowel line is not a tie line
            if (p.get("role_hint") == "dowel") != (s.get("role_hint") == "dowel"):
                continue
            score = 0
            score += 2 if p.get("size") and p.get("size") == s.get("size") else 0
            score += 1 if p.get("role_hint") and p.get("role_hint") == s.get("role_hint") else 0
            if p.get("spacing_mm") is not None and s.get("spacing_mm") is not None:
                score += 1 if abs(p["spacing_mm"] - s["spacing_mm"]) <= SPACING_TOL_MM else 0
            scored.append((-score, i, j))
    for _, i, j in sorted(scored):
        if i in used_p or j in used_s:
            continue
        used_p.add(i)
        used_s.add(j)
        pairs.append((i, j))
    left_p = [i for i in range(len(plan)) if i not in used_p]
    left_s = [j for j in range(len(shop)) if j not in used_s]
    return sorted(pairs), left_p, left_s


def _record(prop: str, plan: Any, shop: Any, relation: str, by: str, **extra: Any) -> dict:
    return {"property": prop, "plan": plan, "shop": shop, "result": relation, "by": by, **extra}


def _client_ask(client: LlmClient, state: dict):
    def ask(label: str, plan_text: str, shop_text: str):
        c = client.choose(P.PROPERTY_SYSTEM, _property_prompt(label, plan_text, shop_text), P.PROPERTY_OPTIONS, version=P.PROPERTY_VERSION)
        state["calls"] = state.get("calls", 0) + 1
        return c.option, c.certainty

    return ask


def _property_prompt(label: str, plan_text: str, shop_text: str) -> str:
    return f"PLAN: {label} {plan_text}\nSHOP: {label} {shop_text}\nANSWER:"


def compare_elements(plan_el: dict, shop_el: dict, ask, llm_state: dict | None = None) -> dict[str, list]:
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
        p, s = pbars[i], sbars[j]
        layout = _bar_layout(p)
        base = f"{layout} bars"
        texts = {"plan_text": p.get("source_text"), "shop_text": s.get("source_text")}
        fields = []
        pc, sc = _total_count(p), _total_count(s)
        if (p.get("secondary_count") is None) != (s.get("secondary_count") is None):
            info.append(_record(base, _bar_text(p), _bar_text(s), "not_comparable", "rule", **texts))
            continue
        different_groups = bool(p.get("size") and s.get("size") and p["size"] != s["size"] and pc is not None and sc is not None and pc != sc)
        if different_groups:
            # different size and different count: two different bar groups, not one group that changed
            info.append(_record(base, _bar_text(p), _bar_text(s), "not_comparable", "rule", **texts))
            continue
        if pc is not None and sc is not None:
            fields.append(("count", pc, sc, pc == sc))
        if p.get("secondary_count") is not None and s.get("secondary_count") is not None:
            fields.append(("secondary count", p["secondary_count"], s["secondary_count"], p["secondary_count"] == s["secondary_count"]))
        if p.get("size") and s.get("size"):
            fields.append(("size", p["size"], s["size"], p["size"] == s["size"]))
        if p.get("spacing_mm") is not None and s.get("spacing_mm") is not None:
            fields.append(("spacing mm", p["spacing_mm"], s["spacing_mm"], abs(p["spacing_mm"] - s["spacing_mm"]) <= SPACING_TOL_MM))
        if fields and not any(f[3] for f in fields):
            # nothing in this pair agrees: two different notes, not one note with a changed number
            info.append(_record(base, _bar_text(p), _bar_text(s), "not_comparable", "rule", **texts))
            continue
        for name, pv, sv, same in fields:
            rec = _record(f"{base} {name}", pv, sv, "equal" if same else "different", "rule", **texts)
            (checks if same else flags).append(rec)
        if not fields:
            info.append(_record(base, _bar_text(p), _bar_text(s), "not_comparable", "rule", **texts))
    # leftovers: one plan property and one shop property per question
    for i in left_p:
        placed = False
        for j in left_s:
            ans = ask("vertical or tie bars", _bar_text(pbars[i]), _bar_text(sbars[j]))
            if ans and ans[0] == "same":
                checks.append(_record("bars", _bar_text(pbars[i]), _bar_text(sbars[j]), "equal", "llm", llm_certainty=ans[1]))
                left_s.remove(j)
                placed = True
                break
            if ans and ans[0] == "different" and _numbers_differ(pbars[i], sbars[j]):
                info.append(_record("bars", _bar_text(pbars[i]), _bar_text(sbars[j]), "possible_difference", "llm", llm_certainty=ans[1]))
                left_s.remove(j)
                placed = True
                break
        if not placed:
            info.append(_record("bars", _bar_text(pbars[i]), None, "plan_only", "rule", plan_text=pbars[i].get("source_text")))
    for j in left_s:
        info.append(_record("bars", None, _bar_text(sbars[j]), "shop_only", "rule", shop_text=sbars[j].get("source_text")))
    # characteristics: aligned by name
    pch = {c["name"]: c for c in plan_el.get("characteristics", []) if c["name"] not in {"symbol_size_pt", "size_pt", "shape"}}
    sch = {c["name"]: c for c in shop_el.get("characteristics", []) if c["name"] not in {"symbol_size_pt", "size_pt", "shape", "quantity_required"}}
    for name in sorted(set(pch) | set(sch)):
        p, s = pch.get(name), sch.get(name)
        if p and s:
            if "value_mm" in p and "value_mm" in s and isinstance(p["value_mm"], list):
                same = all(abs(a - b) <= SECTION_TOL_MM for a, b in zip(p["value_mm"], s["value_mm"], strict=False))
                pv, sv = p["value_mm"], s["value_mm"]
            elif "value_mm" in p and "value_mm" in s:
                same = abs(p["value_mm"] - s["value_mm"]) <= SECTION_TOL_MM
                pv, sv = p["value_mm"], s["value_mm"]
            else:
                pv, sv = p["value"], s["value"]
                same = str(pv).strip().lower() == str(sv).strip().lower()
            rec = _record(name, pv, sv, "equal" if same else "different", "rule", plan_text=p.get("source_text"), shop_text=s.get("source_text"))
            # outside the reinforcement itself (section, elevation, concrete): evidence for the pairing,
            # listed for the engineer, never a non-conformity on its own
            (checks if same else info).append(rec)
        elif p:
            info.append(_record(name, p["value"], None, "plan_only", "rule", plan_text=p.get("source_text")))
        else:
            info.append(_record(name, None, s["value"], "shop_only", "rule", shop_text=s.get("source_text")))
    return {"checks": checks, "flags": flags, "info": info}


STRONG = ("secondary count", "spacing mm", "type")  # values specific enough to identify a note


def evidence_weight(checks: list[dict]) -> int:
    """How much the agreeing values say that the two notes are the same element. A bar size or a
    count that agrees is weak (most notes share them); a spacing, a secondary count or a type code
    that agrees is strong; an agreeing section is weak evidence too."""
    w = 0
    for c in checks:
        prop = c["property"]
        if any(k in prop for k in STRONG):
            w += 2
        elif prop.endswith(("count", "size")) or prop == "section":
            w += 1
    return w


def combined(elements: list[dict]) -> dict:
    """All the statements about one member at one place and level, from several notes: a column strip
    prints its vertical bars and its ties as two notes, a slab cell can carry several bar lines.
    Identical statements (the same note printed on two sheets) count once."""
    bars, seen = [], set()
    chars: dict[str, dict] = {}
    type_key = None
    for e in elements:
        for b in e.get("bars", []):
            key = (b.get("role_hint"), b.get("count"), b.get("size"), b.get("secondary_count"), b.get("spacing_mm"), b.get("source_text"))
            if key not in seen:
                seen.add(key)
                bars.append(b)
        for c in e.get("characteristics", []):
            chars.setdefault(c["name"], c)
        type_key = type_key or e.get("type_key")
    return {"bars": bars, "characteristics": list(chars.values()), "type_key": type_key}


def identity_score(ent, shop_el: dict, shop_cell: str | None) -> int:
    """How sure the pairing is that the plan and shop elements are one member, from where and what
    they are (not from their values): the same grid cell (2) or a neighbouring cell the plan note sits
    between (1); a shop location written in the shop's own text or strip label (+1); the same known
    kind (+1); the same level (+1)."""
    score = 2 if shop_cell and shop_cell == ent.cell else (1 if shop_cell and shop_cell in ent.alts else 0)
    g = _loc(shop_el, "grid") or {}
    if _loc(shop_el, "grid_cells") or g.get("basis") == "strip_label":
        score += 1
    if ent.kind and shop_el.get("kind") and ent.kind == shop_el.get("kind"):
        score += 1
    lv = _loc(shop_el, "level") or {}
    if ent.level and ent.level == lv.get("value"):
        score += 1
    return score


CONFIRM_IDENTITY = 4  # pairing evidence needed to call a difference without a distinctive value agreeing


def confirm(out: dict, identity: int) -> None:
    """Keep a difference as a non-conformity when the evidence says it is one member with a changed
    value: a distinctive value of the same bar group agrees (a spacing, a secondary count), or the
    agreeing values of the pair weigh 2 or more. Otherwise it becomes a possible difference for review."""
    content = evidence_weight(out["checks"])
    kept, doubtful = [], []
    for fl in out["flags"]:
        same_group = [
            c for c in out["checks"]
            if c.get("plan_text") == fl.get("plan_text") and c.get("shop_text") == fl.get("shop_text")
        ]
        strong = any(any(k in c["property"] for k in ("spacing mm", "secondary count")) for c in same_group)
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
        return abs(p["spacing_mm"] - s["spacing_mm"]) > SPACING_TOL_MM
    return False


def _ref(e: dict) -> dict:
    return {"element_id": e["id"], "file": e["file"], "sheet": e.get("sheet"), "page": e["page"], "x": e["x"], "y": e["y"]}


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
        wanted.setdefault(_property_prompt(label, plan_text, shop_text), (label, plan_text, shop_text))
        return None

    def sides(pair: dict) -> tuple[dict, dict, list[dict]]:
        ent = entities[pair["plan_entity"]]
        shop_members = [by_id[i] for i in pair.get("shop_elements", [pair["shop_element"]]) if i in by_id]
        return combined(ent.members), combined(shop_members), shop_members

    for pair in res.pairs:
        p_side, s_side, _ = sides(pair)
        compare_elements(p_side, s_side, collect)
    prompts = list(wanted)
    got = choose_many(client, P.PROPERTY_SYSTEM, prompts, P.PROPERTY_OPTIONS, version=P.PROPERTY_VERSION)
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
        out = compare_elements(plan_el, shop_side, answer)
        # quantity: how many plan elements the shop line says it covers
        qty = next((c["value"] for c in shop_el.get("characteristics", []) if c["name"] == "quantity_required"), None)
        cells = _loc(shop_el, "grid_cells")
        if qty is not None and cells:
            n_matched = len(matched_per_shop[shop_el["id"]])
            if n_matched == len(cells["cells"]):
                rec = _record("quantity required", n_matched, qty, "equal" if n_matched == qty else "different", "rule")
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
                "match": {"cost": pair["cost"], "llm_certainty": pair["llm_certainty"], "method": pair["method"], "identity": identity},
                "notes": notes,
                "order": n,
            }
        )
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
                "info": [_record("presence", "on plan", "no shop counterpart found", "unmatched", "rule")],
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
                "location": {"grid": (_loc(e, "grid") or {}).get("cell") or ", ".join((_loc(e, "grid_cells") or {}).get("cells", []))},
                "members": {"plan": [], "shop": [_ref(e)]},
                "status": "not_in_plan",
                "checks": [],
                "flags": [],
                "info": [_record("presence", "no plan counterpart found", "in shop drawings", "unmatched", "rule")],
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
        "entities": records,
    }
