"""Pair plan elements with shop elements by match key (level, grid row, grid column)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from l2c.contract.models import ElementExt

NEAR_COL_MAX = (
    0.5  # fractional gridlines: a decimal line and its neighbour differ by less than this
)


@dataclass
class Pair:
    plan: ElementExt | None
    shop: ElementExt | None
    method: str  # key | near_col | none | unbound
    cost: float | None = None
    margin: float | None = None
    extra_shop: list[ElementExt] = field(default_factory=list)
    extra_plan: list[ElementExt] = field(default_factory=list)


def _complete(e: ElementExt) -> bool:
    k = e.match_key
    return k.row is not None and k.col is not None


def _rank(e: ElementExt) -> tuple[float, str, int, str]:
    return (-e.quality.overall, e.fichier, e.page, e.id)


def match(plan: list[ElementExt], shop: list[ElementExt]) -> list[Pair]:
    pairs: list[Pair] = []
    index: dict[str, list[ElementExt]] = {}
    for e in shop:
        if _complete(e):
            index.setdefault(e.match_key.key_str(), []).append(e)
    for group in index.values():
        group.sort(key=_rank)
    used: set[str] = set()
    pending_plan: list[ElementExt] = []
    plan_index: dict[str, list[ElementExt]] = {}
    unbound_plan: list[ElementExt] = []
    for p in plan:
        if _complete(p):
            plan_index.setdefault(p.match_key.key_str(), []).append(p)
        else:
            unbound_plan.append(p)
    for group in plan_index.values():
        group.sort(key=_rank)  # the same element drawn on several sheets: best quality leads
    primaries = sorted(
        ((g[0], g[1:]) for g in plan_index.values()),
        key=lambda t: (t[0].level, t[0].match_key.row or "", t[0].match_key.col or 0, t[0].id),
    )
    for p in sorted(unbound_plan, key=lambda e: (e.level, e.id)):
        pairs.append(Pair(p, None, "unbound"))
    extras_of = {p.id: extras for p, extras in primaries}
    for p, extras in primaries:
        key = p.match_key.key_str()
        if key in index and key not in used:
            primary, *shop_extras = index[key]
            pairs.append(Pair(p, primary, "key", extra_shop=shop_extras, extra_plan=list(extras)))
            used.add(key)
        else:
            pending_plan.append(p)

    free = {k: v for k, v in index.items() if k not in used}
    still_plan: list[ElementExt] = []
    by_group: dict[tuple[str, str, str], list[ElementExt]] = {}
    for p in pending_plan:
        k = p.match_key
        by_group.setdefault((k.type, k.level, k.row or ""), []).append(p)
    free_by_group: dict[tuple[str, str, str], list[str]] = {}
    for key, group in free.items():
        k = group[0].match_key
        free_by_group.setdefault((k.type, k.level, k.row or ""), []).append(key)
    for gk, plist in sorted(by_group.items()):
        shop_keys = sorted(free_by_group.get(gk, []))
        if not shop_keys:
            still_plan.extend(plist)
            continue
        cost = np.array(
            [
                [abs((p.match_key.col or 0) - (free[sk][0].match_key.col or 0)) for sk in shop_keys]
                for p in plist
            ]
        )
        ri, cj = linear_sum_assignment(cost)
        assigned: set[int] = set()
        for i, j in zip(ri, cj, strict=True):
            c = float(cost[i, j])
            if c > NEAR_COL_MAX:
                continue
            others = np.delete(cost[i], j)
            runner = float(others.min()) if others.size else float("inf")
            margin = (
                1.0
                if runner == float("inf")
                else max(0.0, (runner - c) / runner if runner else 0.0)
            )
            primary, *extras = free[shop_keys[j]]
            pairs.append(
                Pair(
                    plist[i],
                    primary,
                    "near_col",
                    round(c, 3),
                    round(margin, 3),
                    extras,
                    extras_of[plist[i].id],
                )
            )
            used.add(shop_keys[j])
            assigned.add(i)
        still_plan.extend(p for i, p in enumerate(plist) if i not in assigned)
    for p in still_plan:
        pairs.append(Pair(p, None, "none", extra_plan=extras_of[p.id]))
    for key in sorted(k for k in index if k not in used):
        primary, *extras = index[key]
        pairs.append(Pair(None, primary, "none", extra_shop=extras))
    for e in sorted((s for s in shop if not _complete(s)), key=lambda e: (e.fichier, e.page, e.id)):
        pairs.append(Pair(None, e, "unbound"))
    return pairs
