"""OCR for pages without a text layer (vector-outlined or image-only sheets).

Local, CPU-only, deterministic with fixed weights: RapidOCR (ONNX) on tiles of the rendered page.
Pipeline: pick the orientations worth reading -> render tiles -> read lines -> split lines into
words -> map back to PDF points (displayed frame) -> drop overlap duplicates -> snap to the
vocabulary. Every size and threshold comes from the Config.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pymupdf

from l2c.extract.config import DEFAULT_CONFIG, Config
from l2c.ingest.pages import PageData, Word, load_pdf, title_block_sheet
from l2c.ingest.snap import snap_token

ROTATIONS = (0, 90, 270)  # degrees the text is turned clockwise in the image
# strict on purpose: only real notation counts as evidence for an orientation
COUNT_SIZE = re.compile(r"\d{1,2}\s?-\s?\d{2}\s?M\b", re.IGNORECASE)
MIN_INK = 0.00002  # only tiles with essentially no ink are skipped (labels are tiny)
DEDUP_IOU = 0.5
CONTAINED_SHARE = 0.6  # a box mostly inside a better one is a fragment of it
GHOST_SWALLOWED = 2  # a word covering this many better words is a misreading of them
GHOST_SHARE = 0.4  # ... where each of them lies at least this much inside it


_THREADS = -1  # ONNX threads per model; -1 = all cores. Parallel workers use fewer.
_USE_CLS = True  # the text-angle classifier; sheets are upright, so it can be skipped


def set_engine_options(threads: int | None = None, use_cls: bool | None = None) -> None:
    """Set before the first OCR call in a process (a worker shares the cores with its siblings)."""
    global _THREADS, _USE_CLS
    if threads is not None:
        _THREADS = threads
    if use_cls is not None:
        _USE_CLS = use_cls
    engine.cache_clear()


def set_engine_threads(n: int) -> None:
    set_engine_options(threads=n)


REPO = Path(__file__).resolve().parents[3]
VENDOR = REPO / "data" / "vendor"
_GPU_ACTIVE = False


def _enable_gpu() -> bool:
    """Use the CUDA build of onnxruntime kept under data/vendor (onnxruntime-gpu for CUDA 12 plus the
    cuDNN libraries). It must be on sys.path before onnxruntime is first imported in this process;
    when that has already happened, or the folder is missing, OCR stays on the CPU. Set
    L2C_OCR_GPU=0 to force the CPU."""
    import glob
    import os
    import sys

    global _GPU_ACTIVE
    if os.environ.get("L2C_OCR_GPU", "1") == "0" or not (VENDOR / "ortgpu").is_dir():
        return False
    if "onnxruntime" in sys.modules:
        return _GPU_ACTIVE
    sys.path.insert(0, str(VENDOR / "ortgpu"))
    dirs = glob.glob(str(VENDOR / "ortgpu" / "nvidia" / "*" / "bin")) + glob.glob(str(VENDOR / "ortgpu_cudnn" / "nvidia" / "*" / "bin"))
    dirs += glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin"))
    for d in dirs:
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(d)
    _GPU_ACTIVE = True
    return True


@lru_cache(maxsize=1)
def engine():
    gpu = _enable_gpu()
    from rapidocr_onnxruntime import RapidOCR

    kwargs = {
        f"{part}_{kind}_op_num_threads": _THREADS
        for part in ("det", "cls", "rec")
        for kind in ("intra", "inter")
    }
    if gpu:
        kwargs.update(det_use_cuda=True, cls_use_cuda=True, rec_use_cuda=True)
    return RapidOCR(use_cls=_USE_CLS, **kwargs)


def release_engine() -> None:
    """Free the OCR engine (and its GPU memory) so the language model can have the card."""
    import gc

    engine.cache_clear()
    gc.collect()


@dataclass(frozen=True)
class OcrResult:
    words: list[Word]
    orientations: tuple[int, ...]
    snapped: int
    mean_conf: float


def render(page: pymupdf.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


def ink(tile: np.ndarray) -> float:
    return float((tile.mean(axis=2) < 128).mean())


def tiles(img: np.ndarray, tile_px: int, overlap: float):
    """Yield (tile, x offset, y offset) covering the image with the given overlap."""
    h, w = img.shape[:2]
    step = max(1, int(tile_px * (1 - overlap)))
    for y in range(0, max(h - int(tile_px * overlap), 1), step):
        for x in range(0, max(w - int(tile_px * overlap), 1), step):
            yield img[y : y + tile_px, x : x + tile_px], x, y


def to_tile_frame(xp: float, yp: float, rotation: int, w: int, h: int) -> tuple[float, float]:
    """Map a point of the image turned counter-clockwise by `rotation` back to the tile.

    np.rot90(T, 1): new[i, j] = T[j, w-1-i]   ->  tile point (x, y) = (w - y', x')
    np.rot90(T, 3): new[i, j] = T[h-1-j, i]   ->  tile point (x, y) = (y', h - x')
    """
    if rotation == 0:
        return xp, yp
    if rotation == 90:
        return w - yp, xp
    return yp, h - xp  # 270


def read_tile(
    tile: np.ndarray, rotation: int
) -> list[tuple[float, float, float, float, str, float]]:
    """OCR one tile; boxes (x0, y0, x1, y1) are in the tile's own pixels."""
    h, w = tile.shape[:2]
    turned = np.ascontiguousarray(np.rot90(tile, rotation // 90))
    result, _ = engine()(turned)
    out = []
    for box, text, conf in result or []:
        pts = [to_tile_frame(px, py, rotation, w, h) for px, py in box]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out.append((min(xs), min(ys), max(xs), max(ys), text, float(conf)))
    return out


def line_to_words(
    box: tuple[float, float, float, float], text: str, conf: float, rotation: int
) -> list[tuple[float, float, float, float, str, float]]:
    """Split an OCR line into words, sharing the box in proportion to word length."""
    tokens = text.split()
    if not tokens:
        return []
    x0, y0, x1, y1 = box
    weights = [len(t) for t in tokens]
    total = sum(weights) + max(len(tokens) - 1, 0)
    out, cursor = [], 0.0
    for tok, wt in zip(tokens, weights, strict=True):
        a, b = cursor / total, (cursor + wt) / total
        cursor += wt + 1
        if rotation == 0:
            out.append((x0 + a * (x1 - x0), y0, x0 + b * (x1 - x0), y1, tok, conf))
        elif rotation == 90:  # text reads downward
            out.append((x0, y0 + a * (y1 - y0), x1, y0 + b * (y1 - y0), tok, conf))
        else:  # 270: text reads upward
            out.append((x0, y1 - b * (y1 - y0), x1, y1 - a * (y1 - y0), tok, conf))
    return out


def _iou(a: Word, b: Word) -> float:
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    union = (a.x1 - a.x0) * (a.y1 - a.y0) + (b.x1 - b.x0) * (b.y1 - b.y0) - inter
    return inter / union if union > 0 else 0.0


def _inside(a: Word, b: Word) -> float:
    """Share of a's area that lies inside b."""
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    area = (a.x1 - a.x0) * (a.y1 - a.y0)
    return ix * iy / area if area > 0 else 0.0


def dedupe(words: list[Word]) -> list[Word]:
    """Remove duplicates from overlapping tiles and orientations.

    Longer, more confident readings win; a word mostly covered by one already kept is dropped.
    """
    kept: list[Word] = []
    for w in sorted(words, key=lambda w: (-len(w.text) * (w.conf or 0.0), w.y0, w.x0, w.text)):
        same = any(k.text == w.text and _iou(k, w) > DEDUP_IOU for k in kept)
        covered = any(_inside(w, k) >= CONTAINED_SHARE for k in kept)
        if not (same or covered):
            kept.append(w)
    kept = [w for w in kept if not _is_ghost(w, kept)]
    return sorted(kept, key=lambda w: (round(w.y0, 1), w.x0, w.text))


def _is_ghost(w: Word, kept: list[Word]) -> bool:
    """A low-confidence word lying over several better-read words is a bad reading of that text
    (the same line read twice from overlapping tiles, the longer misreading winning on length)."""
    better = [
        k
        for k in kept
        if k is not w
        and (k.conf or 0.0) > (w.conf or 0.0)
        and _inside(k, w) >= GHOST_SHARE
        and k.text != w.text
    ]
    return len(better) >= GHOST_SWALLOWED


def choose_orientations(img: np.ndarray, config: Config) -> tuple[int, ...]:
    """Read the orientation(s) that actually contain rebar notation, probed on the inkiest tiles."""
    cands = sorted(
        tiles(img, config.ocr_tile_px, config.ocr_overlap_fraction),
        key=lambda t: (-ink(t[0]), t[2], t[1]),
    )[: config.ocr_probe_tiles]
    hits = {r: 0 for r in ROTATIONS}
    for tile, _, _ in cands:
        for r in ROTATIONS:
            hits[r] += sum(
                1
                for *_, text, c in read_tile(tile, r)
                if c >= config.ocr_min_conf and _is_notation(text, config)
            )
    best = max(hits.values())
    if best == 0:
        return (0,)
    return tuple(r for r in ROTATIONS if hits[r] >= max(1, config.ocr_min_orientation_share * best))


def ocr_page(
    page: pymupdf.Page,
    config: Config = DEFAULT_CONFIG,
    orientations: tuple[int, ...] | None = None,
) -> OcrResult:
    img = render(page, config.ocr_dpi)
    scale = 72.0 / config.ocr_dpi
    if orientations is None:
        orientations = choose_orientations(img, config) if config.ocr_orientation_probe else (0,)
    words: list[Word] = []
    for tile, ox, oy in tiles(img, config.ocr_tile_px, config.ocr_overlap_fraction):
        if ink(tile) < MIN_INK:
            continue
        for r in orientations:
            for x0, y0, x1, y1, text, conf in read_tile(tile, r):
                if conf < config.ocr_min_conf:
                    continue
                for wx0, wy0, wx1, wy1, tok, c in line_to_words((x0, y0, x1, y1), text, conf, r):
                    snapped, changed = snap_token(tok, config)
                    words.append(
                        Word(
                            snapped,
                            (ox + wx0) * scale,
                            (oy + wy0) * scale,
                            (ox + wx1) * scale,
                            (oy + wy1) * scale,
                            round(c, 3),
                            tok if changed else None,
                        )
                    )
    words = dedupe(words)
    mean = sum(w.conf or 0.0 for w in words) / len(words) if words else 0.0
    return OcrResult(words, orientations, sum(1 for w in words if w.original), round(mean, 3))


def ocr_pdf_page(path: Path, page_number: int, config: Config = DEFAULT_CONFIG) -> OcrResult:
    with pymupdf.open(path) as doc:
        return ocr_page(doc[page_number - 1], config)


def _is_notation(text: str, config: Config) -> bool:
    """Strict on purpose: only the configured keywords or a count-size form count as evidence."""
    words = {k.rstrip(".:").strip() for k in config.keywords()}
    return bool(COUNT_SIZE.search(text)) or any(
        re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE) for w in words if w
    )


def with_ocr_words(page: PageData, result: OcrResult, config: Config = DEFAULT_CONFIG) -> PageData:
    """A copy of the page whose words come from OCR, so the normal extractors can run on it.

    The sheet id lives in the title block, which a text-less page only has after OCR.
    """
    sheet = title_block_sheet(result.words, page.width, page.height, config)
    return replace(page, words=result.words, source="ocr", feuillet=sheet or page.feuillet)


def load_with_ocr(path: Path, fichier: str, config: Config = DEFAULT_CONFIG) -> list[PageData]:
    pages = load_pdf(path, fichier, config)
    out = []
    for p in pages:
        if len(p.words) < config.min_words_native and p.layer in {"vector", "image"}:
            out.append(with_ocr_words(p, ocr_pdf_page(path, p.page, config)))
        else:
            out.append(p)
    return out


CACHE_VERSION = "1"  # bump when the OCR pipeline changes what it returns for the same page


def cache_key(path: Path, page_number: int, config: Config) -> str:
    """Identity of one OCR reading: the file (path, size, modification time), the page and every
    setting that changes the words that come out."""
    st = Path(path).stat()
    raw = "|".join(
        str(x)
        for x in (
            Path(path).resolve(),
            st.st_size,
            st.st_mtime_ns,
            page_number,
            config.ocr_dpi,
            config.ocr_tile_px,
            config.ocr_overlap_fraction,
            config.ocr_min_conf,
            config.ocr_orientation_probe,
            config.bar_sizes,
            CACHE_VERSION,
        )
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def cached_ocr_page(
    path: Path, page_number: int, config: Config = DEFAULT_CONFIG, cache_dir: Path | None = None
) -> OcrResult:
    """`ocr_pdf_page` with an on-disk cache: a page is read once per (file, settings)."""
    if cache_dir is None:
        return ocr_pdf_page(path, page_number, config)
    cache_dir = Path(cache_dir)
    entry = cache_dir / f"{cache_key(path, page_number, config)}.pkl"
    if entry.is_file():
        try:
            return pickle.loads(entry.read_bytes())
        except Exception:  # a damaged entry is simply read again
            pass
    result = ocr_pdf_page(path, page_number, config)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = entry.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(pickle.dumps(result))
    tmp.replace(entry)  # atomic: a reader never sees half a file
    return result
