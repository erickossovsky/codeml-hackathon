"""python -m l2c.free <pdf-or-project-dir> --out <dir> [--ocr] [--pages 1,2]"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

from l2c.contract.io import dumps
from l2c.extract.config import DEFAULT_CONFIG
from l2c.free.reader import read_page
from l2c.ingest.pages import load_pdf


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--source", choices=["plan", "shop", "auto"], default="auto")
    ap.add_argument("--pages", default=None, help="comma separated 1-based pages (single pdf)")
    args = ap.parse_args()
    pdfs = [args.path] if args.path.is_file() else sorted(args.path.rglob("*.pdf"))
    root = args.path.parent if args.path.is_file() else args.path
    wanted = {int(p) for p in args.pages.split(",")} if args.pages else None
    elements, summaries = [], []
    for pdf in pdfs:
        rel = pdf.relative_to(root).as_posix()
        source = args.source
        if source == "auto":  # a PDF inside a DA folder is a shop drawing, one beside it is a plan
            source = "shop" if any(part.upper() == "DA" for part in pdf.parts) or pdf.parent != root else "plan"
        pages = load_pdf(pdf, rel, DEFAULT_CONFIG)
        with pymupdf.open(pdf) as doc:
            for pg in pages:
                if wanted and pg.page not in wanted:
                    continue
                if args.ocr:
                    from l2c.extract.pipeline import prepare_page

                    pg = prepare_page(pg, pdf, True, DEFAULT_CONFIG)
                els, summ = read_page(pg, doc[pg.page - 1], source, DEFAULT_CONFIG)
                elements += els
                summaries.append(summ)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "elements.free.json").write_text(
        dumps([e.model_dump(mode="json") for e in elements]), encoding="utf-8"
    )
    (args.out / "pages.free.json").write_text(
        dumps([s.model_dump(mode="json") for s in summaries]), encoding="utf-8"
    )
    print(f"{len(elements)} elements from {len(summaries)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
