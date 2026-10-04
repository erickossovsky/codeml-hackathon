"""Project-level extraction: PDFs in, MetaBundle out. Deterministic; no ML; no network.

For every page the pipeline decides which adapter fits (`layout`) from what the page contains,
and records that decision. A page that fits no adapter is reported as not covered, never guessed;
an exception on one page never stops the run.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from l2c.contract.io import MetaBundle
from l2c.contract.models import ElementExt, GridSheet, LevelInfo, SheetInfo
from l2c.extract.calibrate import calibrate
from l2c.extract.columns_plan import extract_plan_columns
from l2c.extract.columns_schedule import (
    extract_schedule_columns,
    is_schedule_page,
    schedule_issue,
)
from l2c.extract.columns_shop import extract_shop_columns, find_labels, find_level_lines
from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.extract.grid import Grid, fit_grid
from l2c.extract.learn import learn_config
from l2c.extract.notation import parse_shop_vert, plan_column_level
from l2c.extract.ocr_quality import mark_ocr
from l2c.extract.runs import text_runs
from l2c.ingest.pages import PageData, load_pdf

VERTICAL_TEXT_LIMIT = 0.5  # more than this share of vertical words means rotated text


@dataclass(frozen=True)
class Discovery:
    plans: list[Path]
    shops: list[tuple[Path, str | None]]  # (pdf, element type from the folder name)


def folder_type(rel_parts: tuple[str, ...], config: Config = DEFAULT_CONFIG) -> str | None:
    for part in rel_parts:
        low = part.lower()
        for key, value in config.folder_types:
            if key in low:
                return value
    return None


def _is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"


def discover(project_dir: Path, config: Config = DEFAULT_CONFIG) -> Discovery:
    plans = sorted(p for p in project_dir.iterdir() if _is_pdf(p))
    shops: list[tuple[Path, str | None]] = []
    da = project_dir / "DA"
    if da.is_dir():
        for pdf in sorted(p for p in da.rglob("*") if _is_pdf(p)):
            shops.append((pdf, folder_type(pdf.relative_to(da).parts[:-1], config)))
    return Discovery(plans, shops)


def make_ids_unique(elements: list[ElementExt]) -> list[ElementExt]:
    """Element ids join the metadata to the findings, so they must be unique.

    Ids normally are (sheet or file stem, page and cell). Where two files give the same id the file
    path is put in front, and anything still repeated gets a counter.
    """
    counts = Counter(e.id for e in elements)
    out = []
    for e in elements:
        if counts[e.id] > 1:
            slug = PurePosixPath(e.fichier).with_suffix("").as_posix().replace("/", "_")
            e = e.model_copy(update={"id": f"{slug}__{e.id}"})
        out.append(e)
    seen: Counter[str] = Counter()
    final = []
    for e in out:
        seen[e.id] += 1
        final.append(e if seen[e.id] == 1 else e.model_copy(update={"id": f"{e.id}_{seen[e.id]}"}))
    return final


def has_text(page: PageData, config: Config = DEFAULT_CONFIG) -> bool:
    """Native extraction needs words; the `layer` label only decides whether OCR is needed."""
    return len(page.words) >= config.min_words_native


def _rel(project_dir: Path, path: Path) -> str:
    return path.relative_to(project_dir).as_posix()


def _open_failed(fichier: str, kind: str, etype: str | None, exc: Exception) -> SheetInfo:
    """A file that cannot be opened is recorded and skipped; the rest of the run continues."""
    return SheetInfo(
        fichier=fichier,
        page=0,
        feuillet=None,
        kind=kind,  # type: ignore[arg-type]
        type_element=etype,  # type: ignore[arg-type]
        level=None,
        layer="empty",
        width=0.0,
        height=0.0,
        rotation=0,
        layout=f"error:open_failed:{type(exc).__name__}",
    )


def plan_layout(page: PageData, level: str | None, grid: Grid | None, config: Config) -> str:
    """Which adapter fits a plan page, or why none does."""
    if not has_text(page, config):
        return "needs_ocr" if page.layer in {"vector", "image"} else "empty_page"
    if page.vertical_text > VERTICAL_TEXT_LIMIT:
        return "rotated_text_unsupported"
    if level is None:
        return "not_a_column_plan"
    if grid is None:
        return "plan_blocks_without_grid"
    return "plan_outline"


def shop_layout(page: PageData, etype: str | None, config: Config) -> str:
    if etype != "colonne":
        return f"type_not_supported:{etype or 'unknown'}"
    if not has_text(page, config):
        return "needs_ocr" if page.layer in {"vector", "image"} else "empty_page"
    if page.vertical_text > VERTICAL_TEXT_LIMIT:
        return "rotated_text_unsupported"
    scale = calibrate(page.words, None, config)
    runs = text_runs(page.words, gap=scale.run_gap, split_before=config.keywords())
    verts = [
        r
        for r in runs
        if config.starts(r.text, config.shop_vert) and parse_shop_vert(r.text, config)
    ]
    if not verts:
        if is_schedule_page(page, config):
            return schedule_issue(page, config) or "shop_schedule_table"
        return "no_column_blocks"
    if not find_labels(page.words, config, scale.word_h):
        return "shop_unlabelled_unsupported"
    if not find_level_lines(page, runs, config, scale.word_h):
        return "shop_levels_not_found"  # elements without a level can never be matched
    return "shop_label_strip"


def prepare_page(page: PageData, pdf: Path, use_ocr: bool, config: Config) -> PageData:
    """Replace a text-less page's words with OCR words when OCR is enabled."""
    if use_ocr and not has_text(page, config) and page.layer in {"vector", "image"}:
        from l2c.ingest.ocr import ocr_pdf_page, with_ocr_words

        return with_ocr_words(page, ocr_pdf_page(pdf, page.page, config))
    return page


def extract_project(
    project_dir: Path,
    project: str | None = None,
    config: Config = DEFAULT_CONFIG,
    use_ocr: bool = False,
    learn: bool = True,
) -> MetaBundle:
    found = discover(project_dir, config)
    elements: list[ElementExt] = []
    grids: list[GridSheet] = []
    sheets: list[SheetInfo] = []
    levels: dict[str, LevelInfo] = {}

    def sheet(page: PageData, kind: str, etype, level, layout: str) -> SheetInfo:
        return SheetInfo(
            fichier=page.fichier,
            page=page.page,
            feuillet=page.feuillet if kind == "plan" else None,
            kind=kind,  # type: ignore[arg-type]
            type_element=etype,
            level=level,
            layer=page.layer,  # type: ignore[arg-type]
            width=round(page.width, 2),
            height=round(page.height, 2),
            rotation=page.rotation,
            layout=layout,
        )

    for pdf in found.plans:
        try:
            pages = load_pdf(pdf, _rel(project_dir, pdf), config)
        except Exception as exc:
            sheets.append(_open_failed(_rel(project_dir, pdf), "plan", None, exc))
            continue
        for page in pages:
            level = None
            layout = "unknown"
            etype = None
            cfg = config
            try:
                page = prepare_page(page, pdf, use_ocr, config)
                cfg = learn_config(page.words, config) if learn else config
                text = " ".join(w.text for w in page.words)
                level = plan_column_level(text, cfg)
                grid = fit_grid(page.words, cfg) if has_text(page, cfg) else None
                layout = plan_layout(page, level, grid, cfg)
                if grid is not None and layout in {"plan_outline", "not_a_column_plan"}:
                    grids.append(
                        GridSheet(
                            fichier=page.fichier,
                            page=page.page,
                            feuillet=page.feuillet,
                            letters_on=grid.letters_on,  # type: ignore[arg-type]
                            rows=grid.rows,
                            cols=grid.cols,
                        )
                    )
                if layout in {"plan_outline", "plan_blocks_without_grid"}:
                    etype = "colonne"
                    levels.setdefault(level or "", LevelInfo(level=level or "", name=level or ""))
                    els = extract_plan_columns(page, level or "", grid, cfg)
                    elements.extend(mark_ocr(els, page.words, cfg) if page.source == "ocr" else els)
            except Exception as exc:  # one bad page must not stop the run
                layout = f"error:{type(exc).__name__}"
            sheets.append(sheet(page, "plan", etype, level, layout))

    for pdf, folder in found.shops:
        try:
            pages = load_pdf(pdf, _rel(project_dir, pdf), config)
        except Exception as exc:
            sheets.append(_open_failed(_rel(project_dir, pdf), "shop", folder, exc))
            continue
        for page in pages:
            layout = "unknown"
            try:
                page = prepare_page(page, pdf, use_ocr, config) if folder == "colonne" else page
                cfg = learn_config(page.words, config) if learn else config
                layout = shop_layout(page, folder, cfg)
                if layout in {"shop_label_strip", "shop_schedule_table"}:
                    extractor = (
                        extract_shop_columns
                        if layout == "shop_label_strip"
                        else extract_schedule_columns
                    )
                    els, lvls = extractor(page, cfg)
                    elements.extend(mark_ocr(els, page.words, cfg) if page.source == "ocr" else els)
                    for lv in lvls:
                        current = levels.get(lv.level)
                        if current is None or (
                            current.elevation_mm is None and lv.elevation_mm is not None
                        ):
                            levels[lv.level] = lv
            except Exception as exc:
                layout = f"error:{type(exc).__name__}"
            sheets.append(sheet(page, "shop", folder, None, layout))

    return MetaBundle(
        project=project or project_dir.name,
        elements=make_ids_unique(elements),
        grids=grids,
        levels=[levels[k] for k in sorted(levels)],
        sheets=sheets,
    )
