"""Estimate binding accuracy without labels, using the other document as an independent witness.

A column on the plan that differs from its sheet's usual profile (an *atypical* column) must match
the shop element at the **same grid cell**. If blocks were bound to the wrong cells, atypical
columns would agree with the shop at chance level; typical columns agree almost always and prove
nothing, so they are reported separately and excluded from the estimate. Percentages only.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass

from l2c.contract.io import MetaBundle
from l2c.contract.models import ElementExt


@dataclass(frozen=True)
class Witness:
    matched_cells: int
    typical_total: int
    typical_agree: int
    atypical_total: int
    atypical_agree: int
    chance_total: int
    chance_agree: int

    @property
    def binding_accuracy(self) -> float | None:
        """Lower bound: genuine plan/shop differences also count as disagreement."""
        return self.atypical_agree / self.atypical_total if self.atypical_total else None

    @property
    def chance(self) -> float | None:
        return self.chance_agree / self.chance_total if self.chance_total else None


def _key(e: ElementExt) -> tuple[int | None, str | None]:
    v = e.armature[0] if e.armature else None
    return (v.quantite if v else None, v.diametre if v else None)


def witness(bundle: MetaBundle, seed: int = 1) -> Witness:
    plan = {(e.level, e.grid): e for e in bundle.elements if e.source == "plan" and e.grid}
    shop: dict[tuple[str, str | None], list[ElementExt]] = defaultdict(list)
    for e in bundle.elements:
        if e.source == "shop" and e.grid:
            shop[(e.level, e.grid)].append(e)
    mode: dict[str, Counter] = defaultdict(Counter)
    for (level, _), e in plan.items():
        mode[level][_key(e)] += 1
    usual = {lv: c.most_common(1)[0][0] for lv, c in mode.items()}
    rng = random.Random(seed)
    cells_by_level: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for k in plan:
        if k in shop:
            cells_by_level[k[0]].append(k)
    t_tot = t_ok = a_tot = a_ok = c_tot = c_ok = 0
    for k in sorted(k for ks in cells_by_level.values() for k in ks):
        e = plan[k]
        agree = any(_key(s) == _key(e) for s in shop[k])
        if _key(e) == usual[k[0]]:
            t_tot += 1
            t_ok += agree
        else:
            a_tot += 1
            a_ok += agree
            other = rng.choice(cells_by_level[k[0]])
            c_tot += 1
            c_ok += any(_key(s) == _key(e) for s in shop[other])
    matched = sum(len(v) for v in cells_by_level.values())
    return Witness(matched, t_tot, t_ok, a_tot, a_ok, c_tot, c_ok)
