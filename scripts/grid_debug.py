"""Why is (or is not) the grid found on one page? Counts only, never drawing text.

Usage: python scripts/grid_debug.py <pdf> <page number> [--config overrides.json]
Prints how many letter-like and number-like labels the page has, where they line up, and what
fit_grid decides. Use it when scripts/probe_project.py reports `plan_blocks_without_grid`.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from l2c.extract.config import load_config
from l2c.extract.grid import fit_grid
from l2c.extract.runs import cluster_1d, median_word_height
from l2c.ingest.pages import load_pdf


def lines_of(words, key, tol):
    groups = cluster_1d([key(w) for w in words], tol)
    return sorted((len(g) for g in groups), reverse=True)[:5]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("page", type=int)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()
    config = load_config(args.config)
    page = load_pdf(args.pdf, config=config)[args.page - 1]
    h = median_word_height(page.words)
    tol = config.grid_align_word_heights * h
    letters = [w for w in page.words if re.match(config.grid_letter_pattern, w.text)]
    numbers = [w for w in page.words if re.match(config.grid_number_pattern, w.text)]
    print(f"page {page.page}: {round(page.width)}x{round(page.height)} pt, word height {h:.1f}")
    distinct = len({w.text for w in letters})
    print(f"letters: {len(letters)} (distinct {distinct}), numbers: {len(numbers)}")
    print("letters sharing a column x:", lines_of(letters, lambda w: w.x0, tol))
    print("letters sharing a row y   :", lines_of(letters, lambda w: w.y0, tol))
    print("numbers sharing a column x:", lines_of(numbers, lambda w: w.x0, tol))
    print("numbers sharing a row y   :", lines_of(numbers, lambda w: w.y0, tol))
    repeated = Counter(w.text for w in letters + numbers)
    print(
        "labels that appear 2+ times (mirrored candidates):",
        sum(1 for n in repeated.values() if n >= 2),
    )
    grid = fit_grid(page.words, config)
    if grid is None:
        print("fit_grid: NONE (fewer than", config.grid_min_labels, "labels form an axis)")
    else:
        print(f"fit_grid: letters_on={grid.letters_on} rows={len(grid.rows)} cols={len(grid.cols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
