"""Extract column elements from a plan sheet (`PLAN DES COLONNES - <level>`)."""

from __future__ import annotations

from dataclasses import dataclass

from l2c.contract.models import Armature, ElementExt, MatchKey
from l2c.extract import quality as Q
from l2c.extract.anchor import bind_blocks, find_outlines
from l2c.extract.calibrate import PageScale, calibrate
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import Grid
from l2c.extract.notation import parse_count_size, parse_section, parse_size_spacing
from l2c.extract.runs import Run, text_runs
from l2c.ingest.pages import PageData


@dataclass(frozen=True)
class PlanBlock:
    runs: tuple[Run, ...]
    arm: Run
    col: Run | None
    lig: Run | None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            min(r.x0 for r in self.runs),
            min(r.y0 for r in self.runs),
            max(r.x1 for r in self.runs),
            max(r.y1 for r in self.runs),
        )

    @property
    def text(self) -> str:
        return " | ".join(r.text for r in self.runs)


def assemble_blocks(
    page: PageData, config: Config = DEFAULT_CONFIG, scale: PageScale | None = None
) -> list[PlanBlock]:
    """Group the left-aligned text runs around each block-start run into one annotation block."""
    scale = scale or calibrate(page.words, None, config)
    h = scale.word_h
    runs = text_runs(page.words, gap=scale.run_gap, split_before=config.keywords())
    blocks: list[PlanBlock] = []
    for arm in (r for r in runs if config.starts(r.text, config.block_start)):
        column = sorted(
            (r for r in runs if abs(r.x0 - arm.x0) <= config.x_align_word_heights * h),
            key=lambda r: (r.y0, r.x0),
        )
        i = column.index(arm)
        members = [arm]
        col_run = None
        if (
            i > 0
            and 0 < arm.y0 - column[i - 1].y0 <= config.col_above_word_heights * h
            and config.starts(column[i - 1].text, config.section_line)
        ):
            col_run = column[i - 1]
            members.insert(0, col_run)
        lig_run = None
        prev = arm
        for r in column[i + 1 :]:
            if (
                config.starts(r.text, config.block_start)
                or config.starts(r.text, config.section_line)
                or r.y0 - prev.y0 > config.line_gap_word_heights * h
            ):
                break
            members.append(r)
            if config.starts(r.text, config.ties_line) and lig_run is None:
                lig_run = r
            prev = r
            if (
                config.starts(r.text, config.end_line)
                or r.y0 - arm.y0 > config.block_below_word_heights * h
            ):
                break
        blocks.append(PlanBlock(tuple(members), arm, col_run, lig_run))
    return blocks


def extract_plan_columns(
    page: PageData, level: str, grid: Grid | None, config: Config = DEFAULT_CONFIG
) -> list[ElementExt]:
    scale = calibrate(page.words, grid, config)
    blocks = assemble_blocks(page, config, scale)
    outlines = (
        find_outlines(page.shapes, grid, scale.snap_tol, config.outline_size_tolerance)
        if grid
        else {}
    )
    bindings = bind_blocks(
        [(b.arm.x0, b.arm.y0) for b in blocks], outlines, max_dist=scale.max_bind_dist
    )
    sheet = page.feuillet or page.fichier
    out: list[ElementExt] = []
    unbound = 0
    for block, bind in zip(blocks, bindings, strict=True):
        cs = parse_count_size(block.arm.text, config)
        ties = parse_size_spacing(block.lig.text, config) if block.lig else None
        section = parse_section(block.col.text) if block.col else None
        flags: list[str] = []
        if "GOUJ" in block.arm.text.upper():
            flags.append("dowels_noted")
        if bind is not None:
            grid_cell = f"{bind.row}-{bind.col}"
            row, col = bind.row, float(bind.col)
            loc = Q.location(
                "outline",
                bind.grid_conf,
                anchor_dist_pt=bind.cost,
                grid_cell=grid_cell,
                binding_method="hungarian",
                assignment_cost=bind.cost,
                margin=bind.margin,
            )
            if bind.grid_conf < 0.5:
                flags.append("ambiguous_cell")
            if bind.margin < 0.3:
                flags.append("weak_binding")
            if bind.second_pass:
                flags.append("second_pass_binding")
            element_id = f"{sheet}_{grid_cell}_plan"
        else:
            unbound += 1
            grid_cell, row, col = None, None, None
            loc = Q.location("text_only", 0.1, binding_method="none")
            flags.append("unbound_block")
            element_id = f"{sheet}_U{unbound:03d}_plan"
        attrs = {
            "count": Q.attr(cs.count) if cs else Q.missing_attr(),
            "size": Q.attr(cs.size) if cs else Q.missing_attr(),
            "tie_size": Q.attr(ties.size) if ties else Q.missing_attr(),
            "spacing": Q.attr(ties.spacing_mm) if ties else Q.missing_attr(),
        }
        for name, a in attrs.items():
            if a.status == "missing":
                flags.append(f"{name}_unparsed")
        passed, failed = Q.column_checks(
            cs.count if cs else None,
            cs.size if cs else None,
            ties.spacing_mm if ties else None,
            config,
        )
        x0, y0, x1, y1 = block.bbox
        out.append(
            ElementExt(
                id=element_id,
                source="plan",
                fichier=page.fichier,
                feuillet=page.feuillet,
                page=page.page,
                x=round((x0 + x1) / 2, 2),
                y=round((y0 + y1) / 2, 2),
                type_element="colonne",
                element=grid_cell or element_id,
                armature=[
                    Armature(
                        repere=f"{grid_cell or element_id}-V",
                        diametre=cs.size if cs else None,
                        quantite=cs.count if cs else None,
                    ),
                    Armature(
                        repere=f"{grid_cell or element_id}-T",
                        diametre=ties.size if ties else None,
                        espacement_mm=ties.spacing_mm if ties else None,
                    ),
                ],
                match_key=MatchKey(type="colonne", level=level, row=row, col=col),
                grid=grid_cell,
                level=level,
                section_mm=section,
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                quality=Q.build_quality(
                    type_conf=1.0,
                    level_conf=1.0,
                    loc=loc,
                    attrs=attrs,
                    passed=passed,
                    failed=failed,
                    flags=flags,
                ),
                extraction_method="rules",
                raw_text=block.text,
                provenance={"file": page.fichier, "page": page.page, "adapter": "plan_outline"},
            )
        )
    return out
