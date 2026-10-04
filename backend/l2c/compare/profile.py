"""Comparable reinforcement profile of a column element, and the diff between two profiles."""

from __future__ import annotations

from dataclasses import dataclass

from l2c.contract import constants as C
from l2c.contract.models import Diff, ElementExt


@dataclass(frozen=True)
class Profile:
    count: int | None
    size: str | None
    tie_size: str | None
    spacing_mm: float | None
    tie_count: int | None


def profile(e: ElementExt) -> Profile:
    vert = e.armature[0] if len(e.armature) > 0 else None
    ties = e.armature[1] if len(e.armature) > 1 else None
    return Profile(
        count=vert.quantite if vert else None,
        size=vert.diametre if vert else None,
        tie_size=ties.diametre if ties else None,
        spacing_mm=ties.espacement_mm if ties else None,
        tie_count=ties.quantite if ties else None,
    )


def profile_diffs(plan: Profile, shop: Profile) -> list[Diff]:
    """Only fields present on both sides are compared (the plan never prints a tie count)."""
    out: list[Diff] = []
    if plan.count is not None and shop.count is not None and plan.count != shop.count:
        out.append(
            Diff(field="count", plan=plan.count, shop=shop.count, delta=shop.count - plan.count)
        )
    if plan.size is not None and shop.size is not None and plan.size != shop.size:
        out.append(Diff(field="size", plan=plan.size, shop=shop.size))
    if plan.tie_size is not None and shop.tie_size is not None and plan.tie_size != shop.tie_size:
        out.append(Diff(field="tie_size", plan=plan.tie_size, shop=shop.tie_size))
    if plan.spacing_mm is not None and shop.spacing_mm is not None:
        delta = round(shop.spacing_mm - plan.spacing_mm, 3)
        if abs(delta) > C.SPACING_TOL_MM:
            out.append(
                Diff(field="spacing_mm", plan=plan.spacing_mm, shop=shop.spacing_mm, delta=delta)
            )
    return out


def armature_groups(e: ElementExt) -> dict[str, list[tuple[int | None, float | None]]]:
    """Bar groups keyed by bar size: [(count, spacing_mm), ...]. Works for any element type."""
    groups: dict[str, list[tuple[int | None, float | None]]] = {}
    for a in e.armature:
        if a.diametre is None:
            continue
        groups.setdefault(a.diametre, []).append((a.quantite, a.espacement_mm))
    for g in groups.values():
        g.sort(key=lambda t: (t[0] if t[0] is not None else -1, t[1] if t[1] is not None else -1.0))
    return groups


def _describe(group: list[tuple[int | None, float | None]]) -> str:
    return ", ".join(
        f"{c if c is not None else '?'} bars" + (f" @{s:g}mm" if s is not None else "")
        for c, s in group
    )


def generic_diffs(plan: ElementExt, shop: ElementExt) -> list[Diff]:
    """Type-agnostic comparison: bar groups matched by bar size, fields compared when both exist."""
    pg, sg = armature_groups(plan), armature_groups(shop)
    out: list[Diff] = []
    for size in sorted(set(pg) | set(sg)):
        if size not in sg:
            out.append(Diff(field=f"bar group {size}", plan=_describe(pg[size]), shop=None))
            continue
        if size not in pg:
            out.append(Diff(field=f"bar group {size}", plan=None, shop=_describe(sg[size])))
            continue
        for (pc, ps), (sc, ss) in zip(pg[size], sg[size], strict=False):
            if pc is not None and sc is not None and pc != sc:
                out.append(Diff(field=f"{size} count", plan=pc, shop=sc, delta=sc - pc))
            if ps is not None and ss is not None and abs(ss - ps) > C.SPACING_TOL_MM:
                out.append(
                    Diff(field=f"{size} spacing_mm", plan=ps, shop=ss, delta=round(ss - ps, 3))
                )
        if len(pg[size]) != len(sg[size]):
            out.append(
                Diff(
                    field=f"{size} group count",
                    plan=len(pg[size]),
                    shop=len(sg[size]),
                    delta=len(sg[size]) - len(pg[size]),
                )
            )
    return out
