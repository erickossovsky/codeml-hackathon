"""S3: decide which plan element goes with which shop element.

Code builds the candidates and a base cost from location, level and kind. The LLM is asked one yes/no
question about one plan/shop pair only where several candidates are close, and its probability moves
that pair's cost. The assignment itself is `scipy.optimize.linear_sum_assignment` (the Hungarian
method) in code. The queue of comparisons is ordered by cost, so confident pairs come first.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from l2c.llm import prompts as P
from l2c.llm.client import LlmClient, choose_many
from l2c.llm.compact import element_json

CELL = re.compile(r"^(.+)-(\d+(?:\.\d+)?)$")
NOT_CANDIDATE = 1e3
MAX_COST = 1.8  # an assigned pair above this is rejected
UNMATCHED_COST = 0.8  # cost of leaving one side without a partner (dummy rows and columns)
NOTHING_IN_COMMON = 1.7  # above two unmatched costs: such a pair is never preferred to no pair
SYNONYMS = [{"column", "pier"}, {"wall", "shear_wall"}, {"footing", "raft", "pier"}]
FOUNDATION = {
    "footing",
    "raft",
    "pile",
    "pile_cap",
}  # at the foundation by definition: their level label is not evidence
REL_TOL = 0.04  # inch-to-metric rounding stays under 2%; a real change (a bar size, a spacing step) is about 8% or more


def same_length(a: float, b: float, floor_mm: float = 5.0) -> bool:
    """Two lengths in mm are the same value written in two unit systems or rounded."""
    return abs(a - b) <= max(floor_mm, REL_TOL * max(abs(a), abs(b)))


def _field_equal(k: str, a, b) -> bool:
    return same_length(a, b) if k == "spacing_mm" else a == b


TOP_CANDIDATES = 3  # shop slots asked about per plan element, lowest prior cost first
SECOND_PASS_MAX_COST = 1.7  # relaxed candidates up to this cost are asked about
SECOND_PASS_MIN_CERTAINTY = 0.6


@dataclass
class Entity:
    """One real-world plan element: one or more plan elements describing the same cell and level."""

    id: str
    members: list[dict]
    cell: str | None
    level: str | None
    kind: str | None
    alts: list[str] = field(default_factory=list)  # neighbouring cells the note may belong to
    rc: tuple[float, float] | None = None  # continuous grid position (row rank, column number)

    @property
    def primary(self) -> dict:
        return self.members[0]


@dataclass
class Slot:
    """One grid cell of one shop element (a shop element may cover several cells)."""

    shop: dict
    cell: str | None
    level: str | None
    level_to: str | None
    kind: str | None
    group: list[dict] = field(
        default_factory=list
    )  # other shop elements with the same cell, level and kind
    rc: tuple[float, float] | None = None
    union: dict | None = None  # all bars of the group, for costing


@dataclass
class Result:
    pairs: list[dict] = field(default_factory=list)
    plan_unmatched: list[Entity] = field(default_factory=list)
    shop_unmatched: list[dict] = field(default_factory=list)
    llm_calls: int = 0


def parse_cell(cell: str | None) -> tuple[str, float] | None:
    m = CELL.match(cell or "")
    return (m.group(1), float(m.group(2))) if m else None


def _loc(el: dict, kind: str) -> dict | None:
    return next((loc for loc in el.get("locations", []) if loc["type"] == kind), None)


def _quality_rank(e: dict) -> tuple:
    return (
        -(1 if e["quality"].get("has_facts") else 0),
        e["match"].get("rule_certainty") is None,
        e["id"],
    )


def eligible(e: dict) -> bool:
    return bool(e["quality"].get("has_facts")) and e.get("role") not in {"annotation", "drawing"}


def build_entities(plan: list[dict]) -> list[Entity]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    loose: list[dict] = []
    for e in plan:
        if not eligible(e):
            continue
        grid = _loc(e, "grid")
        level = _loc(e, "level")
        key = (grid["cell"] if grid else None, level["value"] if level else None, e.get("kind"))
        if key[0] is None:
            loose.append(e)
        else:
            groups[key].append(e)
    out = []
    for (cell, level, kind), members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        members.sort(key=_quality_rank)
        g = _loc(members[0], "grid") or {}
        out.append(
            Entity(
                "", members, cell, level, kind, list(g.get("alt_cells", [])), _rc(g.get("rc"), cell)
            )
        )
    for e in loose:
        lv = _loc(e, "level")
        out.append(Entity("", [e], None, lv["value"] if lv else None, e.get("kind")))
    for i, ent in enumerate(out, 1):
        ent.id = f"P{i:05d}"
    return out


def build_slots(shop: list[dict]) -> list[Slot]:
    slots = []
    for e in shop:
        if not eligible(e) or e.get("match", {}).get("method") == "schedule_tag":
            continue  # a schedule copied onto a shop drawing is reference data, not what is fabricated
        lv = _loc(e, "level")
        level = lv["value"] if lv else None
        level_to = lv.get("to") if lv else None
        cells_loc = _loc(e, "grid_cells")
        grid = _loc(e, "grid")
        cells = list(cells_loc["cells"]) if cells_loc else ([grid["cell"]] if grid else [None])
        for c in cells:
            rc = _rc(grid.get("rc") if grid and grid.get("cell") == c else None, c)
            slots.append(Slot(e, c, level, level_to, e.get("kind"), rc=rc))
    return slots


def _rc(rc, cell: str | None) -> tuple[float, float] | None:
    """A continuous grid position: the one measured from the text's position when there is one, else
    the one the cell's labels give (row letter rank, column number)."""
    if rc and None not in rc:
        return (float(rc[0]), float(rc[1]))
    pc = parse_cell(cell)
    if not pc:
        return None
    from l2c.extract.grid import _letter_rank

    try:
        return (float(_letter_rank(pc[0])), pc[1])
    except (TypeError, ValueError):
        return None


def _kind_cost(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 0.2
    if a == b:
        return 0.0
    return (
        0.3 if any(a in s and b in s for s in SYNONYMS) else 2.0
    )  # two different known kinds: not the same object


def _level_cost(plan_level: str | None, s: Slot, kind: str | None = None) -> float:
    if plan_level is None or s.level is None:
        return 0.3
    if plan_level == s.level:
        return 0.0
    if s.level_to and plan_level == s.level_to:
        return 0.4
    if kind in FOUNDATION or s.kind in FOUNDATION:
        return (
            0.3  # a footing's level label (foundation, sub-grade, the storey above) is not evidence
        )
    # two known, different storeys are two different members; reinforcement changes between storeys,
    # so such a pair would read as a changed value
    return NOT_CANDIDATE


def _cell_cost(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 2.0
    if a == b:
        return 0.0
    pa, pb = parse_cell(a), parse_cell(b)
    if pa and pb and pa[0] == pb[0] and abs(pa[1] - pb[1]) <= 1.0:
        return 1.2
    return 2.0


def _section(e: dict) -> tuple | None:
    c = next((c for c in e.get("characteristics", []) if c.get("name") == "section"), None)
    return tuple(c["value_mm"]) if c and c.get("value_mm") else None


def _relaxed_cell_cost(a: str | None, b: str | None) -> float:
    """Second pass: neighbouring row variants (`O` vs `O.1`) or columns up to two apart in one row."""
    c = _cell_cost(a, b)
    if c < 2.0:
        return c
    pa, pb = parse_cell(a), parse_cell(b)
    if not (pa and pb):
        return 2.0
    base_a, base_b = pa[0].split(".")[0].rstrip("'"), pb[0].split(".")[0].rstrip("'")
    if pa[0] == pb[0] and abs(pa[1] - pb[1]) <= 2.0:
        return 1.4
    if base_a == base_b and abs(pa[1] - pb[1]) <= 1.0:
        return 1.4
    return 2.0


def _bar_fields(b: dict) -> dict[str, object]:
    return {
        k: b.get(k)
        for k in ("size", "count", "secondary_count", "spacing_mm")
        if b.get(k) is not None
    }


def _content_cost(a: dict, b: dict) -> float:
    """How alike what the two notes say is: for the most alike pair of bar groups, the share of the
    fields both state (bar size, count, secondary count, spacing) that are equal. A note with one
    number changed is still very alike; two unrelated notes share nothing."""
    if bool(a.get("bars")) != bool(b.get("bars")):
        return NOTHING_IN_COMMON  # one note states bars and the other states none: not the same kind of note
    best = 0.0
    seen = False
    for ba in a.get("bars", []):
        fa = _bar_fields(ba)
        for bb in b.get("bars", []):
            fb = _bar_fields(bb)
            both = fa.keys() & fb.keys()
            if not both:
                continue
            seen = True
            best = max(best, sum(_field_equal(k, fa[k], fb[k]) for k in both) / len(both))
    if not seen:
        return 0.0
    if best == 0:
        return NOTHING_IN_COMMON  # both notes state values and none agree: two different elements
    return round(0.15 - 0.5 * best, 3)  # -0.35 when everything agrees


def _section_cost(a: dict, b: dict) -> float:
    """Equal drawn sections (16"x24") are strong evidence of the same member; different ones are strong evidence against."""
    sa, sb = _section(a), _section(b)
    if not sa or not sb:
        return 0.0
    same = all(same_length(x, y, 1.0) for x, y in zip(sa, sb, strict=True)) or all(
        same_length(x, y, 1.0) for x, y in zip(sa, sb[::-1], strict=True)
    )
    return -0.3 if same else 0.4


def _ent_cell_cost(ent: Entity, s: Slot) -> float:
    if s.cell and s.cell in ent.alts:
        return (
            0.3  # a neighbouring cell the note sits between: the note's content has to confirm it
        )
    return _cell_cost(ent.cell, s.cell)


def _distance(ent: Entity, s: Slot) -> float:
    """Distance in grid units between the plan note and the shop note's cell, used to break ties
    between neighbouring cells (a tag between gridlines K and L that sits nearer L belongs to L)."""
    if not ent.rc or not s.rc:
        return 0.0
    return abs(ent.rc[0] - s.rc[0]) + 0.5 * abs(ent.rc[1] - s.rc[1])


def base_cost(ent: Entity, s: Slot) -> float:
    shop_side = s.union or s.shop
    cost = (
        _ent_cell_cost(ent, s)
        + _level_cost(ent.level, s, ent.kind)
        + _kind_cost(ent.kind, s.kind)
        + _content_cost(ent.primary, shop_side)
    )
    cost += 0.15 * min(_distance(ent, s), 2.0)
    a, b = _section(ent.primary), _section(shop_side)
    if a and b:
        cost += -0.2 if all(same_length(x, y, 1.0) for x, y in zip(a, b, strict=True)) else 0.0
    return round(cost, 3)


def _slot_element(s: Slot) -> dict:
    """The shop element as it applies to one grid cell (a list entry may cover several)."""
    e = dict(s.shop)
    locs = [loc for loc in e.get("locations", []) if loc["type"] == "level"]
    if s.cell:
        locs.insert(0, {"type": "grid", "cell": s.cell})
    e["locations"] = locs
    return e


def _pair_question(ent: Entity, s: Slot) -> str:
    return f"PLAN: {element_json(ent.primary)}\nSHOP: {element_json(_slot_element(s))}\nANSWER:"


CLEAR_MARGIN = 0.2  # a second candidate this close to the best makes the pairing a close call


def _row_of(cell: str | None) -> str | None:
    pc = parse_cell(cell)
    return pc[0].split(".")[0].rstrip("'") if pc else None


def _components(
    n: int, m: int, edges: dict[tuple[int, int], float]
) -> list[tuple[list[int], list[int]]]:
    """Plan entities and slots joined by candidate edges. Each component is solved on its own, so the
    assignment never builds one matrix for the whole project."""
    parent = list(range(n + m))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in edges:
        parent[find(i)] = find(n + j)
    comps: dict[int, tuple[list[int], list[int]]] = {}
    for i, _ in edges:
        comps.setdefault(find(i), ([], []))
    for i in {i for i, _ in edges}:
        comps[find(i)][0].append(i)
    for j in {j for _, j in edges}:
        comps[find(n + j)][1].append(j)
    return [(sorted(set(a)), sorted(set(b))) for a, b in comps.values()]


def _solve(
    rows: list[int], cols: list[int], edges: dict[tuple[int, int], float]
) -> list[tuple[int, int, float]]:
    """Hungarian assignment of one component, with dummy rows and columns so a poor pairing is never forced."""
    r, c = len(rows), len(cols)
    ri = {v: k for k, v in enumerate(rows)}
    ci = {v: k for k, v in enumerate(cols)}
    big = np.zeros((r + c, c + r))
    big[:r, :c] = NOT_CANDIDATE
    for (i, j), v in edges.items():
        if i in ri and j in ci:
            big[ri[i], ci[j]] = v
    big[:r, c:] = np.where(np.eye(r, dtype=bool), UNMATCHED_COST, NOT_CANDIDATE)
    big[r:, :c] = np.where(np.eye(c, dtype=bool), UNMATCHED_COST, NOT_CANDIDATE)
    out = []
    for a, b in zip(*linear_sum_assignment(big), strict=True):
        if a < r and b < c and big[a, b] < NOT_CANDIDATE and big[a, b] <= MAX_COST:
            out.append((rows[a], cols[b], float(big[a, b])))
    return out


def _best_notes(ent: Entity, s: Slot) -> tuple[dict, dict]:
    """Within one cell and level there can be several notes on each side. Pick the plan note and the
    shop note whose content fits best, so a note is compared with the note that says the same kind of
    thing, not with the first one found."""
    best = None
    for pn in ent.members:
        for sn in [s.shop, *s.group]:
            c = _content_cost(pn, sn)
            if best is None or c < best[0]:
                best = (c, pn, sn)
    return best[1], best[2]  # type: ignore[index]


def assign(plan: list[dict], shop: list[dict], client: LlmClient) -> Result:
    entities = build_entities(plan)
    slots = build_slots(shop)
    res = Result()
    res.entities = entities  # type: ignore[attr-defined]
    if not entities or not slots:
        res.plan_unmatched = entities
        res.shop_unmatched = [e for e in shop if eligible(e)]
        return res
    # slots with the same cell, level range and kind say the same thing (several notes on one slab
    # cell): one representative stands for the group, so they are never counted as separate choices
    reps: dict[tuple, int] = {}
    for j, sl in enumerate(slots):
        key = (sl.cell, sl.level, sl.level_to, sl.kind)
        if key in reps:
            slots[reps[key]].group.append(sl.shop)
        else:
            reps[key] = j
    rep_ids = set(reps.values())
    from l2c.pipeline.compare import combined

    for j in rep_ids:
        if slots[j].group:
            slots[j].union = combined([slots[j].shop, *slots[j].group])
    exact: dict[str, list[int]] = defaultdict(list)
    by_row: dict[str, list[int]] = defaultdict(list)
    for j in sorted(rep_ids):
        sl = slots[j]
        if sl.cell:
            exact[sl.cell].append(j)
            row = _row_of(sl.cell)
            if row:
                by_row[row].append(j)
    res.level_unknown = set()  # type: ignore[attr-defined]
    edges: dict[tuple[int, int], float] = {}
    close: list[int] = []  # plan entities whose pairing is a close call
    for i, ent in enumerate(entities):
        pool = [j for c in [ent.cell, *ent.alts] for j in exact.get(c or "", [])] or by_row.get(
            _row_of(ent.cell) or "", []
        )
        if (
            ent.level is None
            and len({slots[j].level for j in pool if _kind_cost(ent.kind, slots[j].kind) < 1.0}) > 1
        ):
            # the plan does not say which level this is and the shop has several: any pairing would be a guess
            res.level_unknown.add(i)  # type: ignore[attr-defined]
            continue
        scored = sorted(((base_cost(ent, slots[j]), j) for j in pool), key=lambda t: (t[0], t[1]))
        scored = [(c, j) for c, j in scored if c < MAX_COST][:TOP_CANDIDATES]
        for c, j in scored:
            edges[(i, j)] = c
        if not scored:
            continue
        best_exact = _ent_cell_cost(ent, slots[scored[0][1]]) == 0
        crowded = len(scored) > 1 and scored[1][0] - scored[0][0] < CLEAR_MARGIN
        if not best_exact or crowded:
            close.append(i)
    certainty: dict[tuple[int, int], float | None] = {}
    asked: list[tuple[int, int]] = []
    per_entity: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for (i, j), c in edges.items():
        per_entity[i].append((c, j))
    for i in close:
        for _c, j in sorted(per_entity[i])[
            :1
        ]:  # the best candidate; a no moves its cost up and the next one wins
            asked.append((i, j))
    answers = choose_many(
        client,
        P.MATCH_SYSTEM,
        [_pair_question(entities[i], slots[j]) for i, j in asked],
        P.OPTIONS,
        version=P.MATCH_VERSION,
    )
    res.llm_calls += len(asked)
    for (i, j), ans in zip(asked, answers, strict=True):
        if ans.option is None:
            continue  # no answer: the cost stays as the evidence set it
        certainty[(i, j)] = ans.certainty
        edges[(i, j)] = round(
            edges[(i, j)] + (-0.3 * (ans.certainty or 0.5) if ans.option == "yes" else 0.8), 3
        )
    matched_plan: set[int] = set()
    matched_slot: set[int] = set()
    for rows, cols in _components(len(entities), len(slots), edges):
        for i, j, c in _solve(rows, cols, edges):
            ent, s = entities[i], slots[j]
            pn, sn = _best_notes(ent, s)
            res.pairs.append(
                {
                    "plan_entity": ent.id,
                    "plan_elements": [m["id"] for m in ent.members],
                    "plan_element_used": pn["id"],
                    "shop_element": sn["id"],
                    "shop_elements": [s.shop["id"], *[g["id"] for g in s.group]],
                    "shop_cell": s.cell,
                    "cost": round(c, 3),
                    "llm_certainty": certainty.get((i, j)),
                    "method": "hungarian+llm" if (i, j) in certainty else "hungarian",
                    "near_cell": _ent_cell_cost(ent, s) > 0,
                }
            )
            matched_plan.add(i)
            matched_slot.add(j)
    _second_pass(entities, slots, matched_plan, matched_slot, res, client, by_row)
    res.pairs.sort(key=lambda p: (p["cost"], p["plan_entity"]))
    res.plan_unmatched = [e for k, e in enumerate(entities) if k not in matched_plan]
    shop_with_match = {slots[j].shop["id"] for j in matched_slot} | {
        g["id"] for j in matched_slot for g in slots[j].group
    }
    res.shop_unmatched = [s for s in shop if eligible(s) and s["id"] not in shop_with_match]
    return res


NEAR_ROWS = 1.3  # a note's text can sit up to about one bay away from what it describes
NEAR_COLS = 2.2
MIN_SAME_SHARE = (
    0.5  # at least half of the fields both notes state must agree to be worth a question
)


def _same_share(a: dict, b: dict) -> float:
    """Best share of agreeing fields between any two bar groups of the two notes."""
    best = 0.0
    for ba in a.get("bars", []):
        fa = _bar_fields(ba)
        for bb in b.get("bars", []):
            fb = _bar_fields(bb)
            both = fa.keys() & fb.keys()
            if both:
                best = max(best, sum(_field_equal(k, fa[k], fb[k]) for k in both) / len(both))
    return best


def _second_pass(
    entities,
    slots,
    matched_plan: set,
    matched_slot: set,
    res: Result,
    client: LlmClient,
    by_row: dict,
) -> None:
    """Try harder for what is left. A note's text can sit up to about a bay away from the member it
    describes, on either document, so candidates are the free shop notes within about one bay (in
    continuous grid coordinates) at a compatible level and kind that say nearly the same thing. One
    question per remaining plan element, about its best candidate. Unmatched elements are fine (shop
    drawings do not cover every element), so only a confident yes creates a pair."""
    free = [j for j in range(len(slots)) if j not in matched_slot and slots[j].rc]
    by_band: dict[int, list[int]] = defaultdict(list)
    for j in free:
        by_band[int(slots[j].rc[0])].append(j)
    batch: list[tuple[float, int, int]] = []
    for i, ent in enumerate(entities):
        if i in matched_plan or not ent.rc or ent.level is None:
            continue
        r0, c0 = ent.rc
        cands = []
        for band in range(int(r0 - NEAR_ROWS) - 1, int(r0 + NEAR_ROWS) + 2):
            for j in by_band.get(band, []):
                s = slots[j]
                dr, dc = abs(s.rc[0] - r0), abs(s.rc[1] - c0)
                if dr > NEAR_ROWS or dc > NEAR_COLS:
                    continue
                lv, kc = _level_cost(ent.level, s, ent.kind), _kind_cost(ent.kind, s.kind)
                if lv >= 1.0 or kc >= 1.0:
                    continue
                shop_side = s.union or s.shop
                share = _same_share(ent.primary, shop_side)
                if share < MIN_SAME_SHARE:
                    continue
                c = (
                    0.4 * (dr + 0.5 * dc)
                    + lv
                    + kc
                    + _content_cost(ent.primary, shop_side)
                    + _section_cost(ent.primary, shop_side)
                )
                if c < SECOND_PASS_MAX_COST:
                    cands.append((round(c, 3), i, j))
        batch += sorted(cands)[:1]
    answers = choose_many(
        client,
        P.MATCH_SYSTEM,
        [_pair_question(entities[i], slots[j]) for _, i, j in batch],
        P.OPTIONS,
        version=P.MATCH_VERSION,
    )
    res.llm_calls += len(batch)
    taken_p: set[int] = set()
    taken_s: set[int] = set()
    confirmed = sorted(
        (
            (c, i, j, ans)
            for (c, i, j), ans in zip(batch, answers, strict=True)
            if ans.option == "yes" and (ans.certainty or 0) >= SECOND_PASS_MIN_CERTAINTY
        ),
        key=lambda t: (-(t[3].certainty or 0), t[0], t[1], t[2]),
    )
    for c, i, j, ans in confirmed:
        if i in taken_p or j in taken_s:
            continue
        ent, s = entities[i], slots[j]
        taken_p.add(i)
        taken_s.add(j)
        pn, sn = _best_notes(ent, s)
        res.pairs.append(
            {
                "plan_entity": ent.id,
                "plan_elements": [m["id"] for m in ent.members],
                "plan_element_used": pn["id"],
                "shop_element": sn["id"],
                "shop_elements": [s.shop["id"], *[g["id"] for g in s.group]],
                "shop_cell": s.cell,
                "cost": c,
                "llm_certainty": ans.certainty,
                "method": "nearby_content_llm",
                "near_cell": True,
            }
        )
    matched_plan |= taken_p
    matched_slot |= taken_s


def summary(res: Result) -> dict[str, Any]:
    return {
        "pairs": len(res.pairs),
        "plan_unmatched": len(res.plan_unmatched),
        "shop_unmatched": len(res.shop_unmatched),
        "llm_calls": res.llm_calls,
    }
