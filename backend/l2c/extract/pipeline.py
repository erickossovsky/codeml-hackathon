"""Project-level extraction: PDFs in, MetaBundle out. Deterministic; no ML; no network.

For every page the pipeline decides which adapter fits (`layout`) from what the page contains,
and records that decision. A page that fits no adapter is reported as not covered, never guessed;
an exception on one page never stops the run.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
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
from l2c.extract.generic import collapse_duplicates, extract_footing_blocks, extract_generic
from l2c.extract.grid import Grid, fit_grid
from l2c.extract.learn import learn_config
from l2c.extract.notation import (
    _plain,
    find_level,
    parse_shop_vert,
    parse_statements,
    plan_column_level,
    sheet_title,
    sheet_type,
)
from l2c.extract.ocr_quality import mark_ocr
from l2c.extract.regions import drawing_regions
from l2c.extract.runs import text_runs
from l2c.ingest.pages import PageData, load_pdf

GENERIC_TYPES = {"fondation", "poutre", "mur_refend", "dalle"}
UNKNOWN_LEVEL = "UNKNOWN"
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
            parts = pdf.relative_to(da).parts
            etype = folder_type(parts[:-1], config) or folder_type((pdf.stem,), config)
            shops.append((pdf, etype))
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
    if etype != "colonne" and etype not in GENERIC_TYPES:
        return f"type_not_supported:{etype or 'unknown'}"
    if not has_text(page, config):
        return "needs_ocr" if page.layer in {"vector", "image"} else "empty_page"
    if page.vertical_text > VERTICAL_TEXT_LIMIT:
        return "rotated_text_unsupported"
    if etype in GENERIC_TYPES:
        return f"generic_{etype}"
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


def needs_ocr(page: PageData, config: Config) -> bool:
    return not has_text(page, config) and page.layer in {"vector", "image"}


def prepare_page(
    page: PageData,
    pdf: Path,
    use_ocr: bool,
    config: Config,
    ocr_done: dict | None = None,
    ocr_cache: Path | None = None,
) -> PageData:
    """Replace a text-less page's words with OCR words when OCR is enabled.

    `ocr_done` holds results already computed in parallel, keyed by (file, page number).
    """
    if use_ocr and needs_ocr(page, config):
        from l2c.ingest.ocr import cached_ocr_page, with_ocr_words

        result = (ocr_done or {}).get((pdf, page.page))
        if result is None:
            result = cached_ocr_page(pdf, page.page, config, ocr_cache)
        if isinstance(result, Exception):
            raise result
        return with_ocr_words(page, result, config)
    return page


def _level_for(etype: str, *texts: str, config: Config) -> tuple[str, float]:
    """Level of a non-column sheet: foundations sit at FDN, otherwise the first level named in the
    given texts (file name, title); `UNKNOWN` (low confidence) when none is named."""
    if etype == "fondation":
        return "FDN", 1.0
    for text in texts:
        found = find_level(text, config)
        if found:
            return found, 1.0
    return UNKNOWN_LEVEL, 0.3


def _extract_other_plan(page: PageData, text: str, grid, config: Config, whole: PageData | None = None):
    """A plan page that is not a column plan: typical details, or beams, walls, slabs and
    foundations read with the generic extractor. Returns (layout, type, level, elements)."""
    title = sheet_title(text, config)
    if any(_plain(k) in _plain(title or text) for k in config.detail_keywords):
        return "typical_details", None, None, []
    etype, type_conf = sheet_type(title, page.feuillet, config)
    if etype == "colonne":
        return "not_a_column_plan", None, None, []
    if etype is None:
        # a page whose element type cannot be told is never guessed; say whether it matters
        has_statements = bool(parse_statements(text, config))
        return ("type_not_found" if has_statements else "no_rebar_annotations"), None, None, []
    level, level_conf = _level_for(etype, title, config=config)
    if etype == "fondation":
        from l2c.extract.generic import extract_footings

        els = extract_footings(page, level, grid, "plan", config, schedule=whole or page)
        if els:
            return "generic_fondation", etype, level, els
    els = extract_generic(page, etype, level, grid, "plan", config, type_conf, level_conf)
    if not els:
        return "no_rebar_annotations", etype, level, []
    return f"generic_{etype}", etype, level, els


def extract_project(
    project_dir: Path,
    project: str | None = None,
    config: Config = DEFAULT_CONFIG,
    use_ocr: bool = False,
    learn: bool = True,
    workers: int = 1,
    ocr_cache: Path | None = None,
    ocr_workers: int = 1,
) -> MetaBundle:
    """Read every PDF of a project into a MetaBundle.

    `workers` > 1 reads pages in a process pool; `ocr_workers` > 1 also OCRs pages in worker
    processes (measured: no faster on the development machine, so it is off by default). The
    result is identical to the sequential run. `ocr_cache` is a folder where OCR readings are kept, so a page
    is read once per file and settings.
    """
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(workers) as pool:
            return _extract(
                project_dir, project, config, use_ocr, learn, pool, ocr_workers, ocr_cache
            )
    return _extract(project_dir, project, config, use_ocr, learn, None, ocr_workers, ocr_cache)


def _extract(project_dir, project, config, use_ocr, learn, pool, workers, ocr_cache) -> MetaBundle:
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

    def load(pdf: Path):
        try:
            return load_pdf(pdf, _rel(project_dir, pdf), config, pool), None
        except Exception as exc:
            return None, exc

    plan_loaded = [(pdf, *load(pdf)) for pdf in found.plans]
    shop_loaded = [(pdf, folder, *load(pdf)) for pdf, folder in found.shops]
    # OCR: pages are read by worker processes (each its own interpreter, a few threads) and kept in
    # the on-disk cache; whatever they could not read is read here, one page at a time
    ocr_done: dict = {}
    if use_ocr and workers > 1:  # here `workers` is the OCR worker count
        jobs = [
            (pdf, page.page)
            for pdf, pages, _ in [*plan_loaded, *[(a, c, d) for a, _, c, d in shop_loaded]]
            for page in pages or []
            if needs_ocr(page, config)
        ]
        if len(jobs) > 1:
            from l2c.ingest.ocr_workers import default_workers, ocr_pages

            ocr_done = ocr_pages(jobs, config, min(workers, default_workers()), ocr_cache)

    for pdf, pages, error in plan_loaded:
        if error is not None:
            sheets.append(_open_failed(_rel(project_dir, pdf), "plan", None, error))
            continue
        drawings = [(w, d, len(parts) > 1) for w in pages for parts in [drawing_regions(w)] for d in parts]
        for whole, page, drawn in drawings:
            level = None
            layout = "unknown"
            etype = None
            cfg = config
            try:
                page = prepare_page(page, pdf, use_ocr, config, ocr_done, ocr_cache)
                cfg = learn_config(page.words, config) if learn else config
                # type and level come from the whole sheet; a drawing may not hold the title block
                text = " ".join(w.text for w in whole.words)
                level = plan_column_level(text, cfg)
                # a drawing on a multi-drawing sheet may show a single row letter (a one-row plan)
                grid_cfg = replace(cfg, grid_min_labels=1) if drawn else cfg
                grid = fit_grid(page.words, grid_cfg) if has_text(page, cfg) else None
                layout = plan_layout(page, level, grid, cfg)
                if layout == "not_a_column_plan":
                    layout, etype, level, els = _extract_other_plan(page, text, grid, cfg, whole)
                    if els:
                        if level != UNKNOWN_LEVEL:
                            levels.setdefault(level, LevelInfo(level=level, name=level))
                        elements.extend(
                            mark_ocr(els, page.words, cfg) if page.source == "ocr" else els
                        )
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

    for pdf, folder, pages, error in shop_loaded:
        if error is not None:
            sheets.append(_open_failed(_rel(project_dir, pdf), "shop", folder, error))
            continue
        for page in pages:
            layout = "unknown"
            try:
                page = prepare_page(page, pdf, use_ocr, config, ocr_done, ocr_cache)
                cfg = learn_config(page.words, config) if learn else config
                layout = shop_layout(page, folder, cfg)
                if folder == "fondation":
                    stem = PurePosixPath(page.fichier).stem
                    text = " ".join(w.text for w in page.words)
                    level, level_conf = _level_for(folder, stem, sheet_title(text, cfg), config=cfg)
                    grid = fit_grid(page.words, cfg)
                    els = extract_footing_blocks(page, level, grid, "shop", cfg)
                    if els:
                        levels.setdefault(level, LevelInfo(level=level, name=level))
                        elements.extend(mark_ocr(els, page.words, cfg) if page.source == "ocr" else els)
                        sheets.append(sheet(page, "shop", folder, level, "shop_footing_blocks"))
                        continue
                if layout.startswith("generic_"):
                    stem = PurePosixPath(page.fichier).stem
                    text = " ".join(w.text for w in page.words)
                    level, level_conf = _level_for(folder, stem, sheet_title(text, cfg), config=cfg)
                    grid = fit_grid(page.words, cfg)
                    els = extract_generic(page, folder, level, grid, "shop", cfg, 0.9, level_conf)
                    if els:
                        if level != UNKNOWN_LEVEL:
                            levels.setdefault(level, LevelInfo(level=level, name=level))
                        elements.extend(
                            mark_ocr(els, page.words, cfg) if page.source == "ocr" else els
                        )
                    else:
                        layout = "no_rebar_annotations"
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
        elements=make_ids_unique(collapse_duplicates(elements)),
        grids=grids,
        levels=[levels[k] for k in sorted(levels)],
        sheets=sheets,
    )
