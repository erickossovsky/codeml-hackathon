"""python -m l2c.pipeline <project_dir> --out <dir> [--llm auto|fake|llama] [--no-ocr] [--force]

Per PDF: raw items (S1) -> unified elements JSON (S2). Across PDFs: assignment (S3) and findings (S4).
Per PDF again: a findings report (S5). A plan is a PDF directly in the project folder; a shop
drawing is a PDF anywhere under its `DA/` folder.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from l2c.contract.io import dumps
from l2c.llm.client import make_client
from l2c.pipeline import assign as A
from l2c.pipeline import compare as C
from l2c.pipeline import lean
from l2c.pipeline.report import Explainer, build_project_report

OCR_CACHE = Path(__file__).resolve().parents[3] / "data" / "cache" / "ocr"


def discover(project: Path) -> list[tuple[Path, str, str]]:
    """(pdf, path relative to the project, source)."""
    out = []
    for pdf in sorted(project.rglob("*.pdf")):
        rel = pdf.relative_to(project).as_posix()
        source = (
            "shop"
            if any(p.upper() == "DA" for p in pdf.relative_to(project).parts[:-1])
            else "plan"
        )
        out.append((pdf, rel, source))
    return out


def _timed(label: str, t0: float) -> float:
    now = time.time()
    print(f"  {label}: {now - t0:.1f}s", flush=True)
    return now


def run(
    project: Path,
    out: Path,
    *,
    llm: str = "auto",
    ocr: bool = True,
    force: bool = False,
    pages: set[int] | None = None,
    files: set[str] | None = None,
    gpu_layers: int = 24,
    workers: int = 6,
    ocr_cache: Path | None = None,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    kw = {"n_gpu_layers": gpu_layers} if llm == "llama" else {}
    t0 = time.time()
    elements: dict[str, dict] = {}
    found = [
        (pdf, rel, source)
        for pdf, rel, source in discover(project)
        if not files or any(f in rel for f in files)
    ]
    t = time.time()
    print(f"reading {len(found)} files with {workers} workers", flush=True)
    read = lean.read_many(
        [(pdf, rel) for pdf, rel, _ in found],
        ocr=ocr,
        pages=pages,
        workers=workers,
        ocr_cache=ocr_cache or OCR_CACHE,
    )
    t = _timed("read text", t)
    from l2c.ingest import ocr as _ocr

    _ocr.release_engine()  # the OCR engine gives the GPU back before the language model starts
    client = make_client(llm, **kw)
    print(f"model: {client.model_id}", flush=True)
    t = time.time()
    questions = 0
    for pdf, rel, source in found:
        data = lean.build_elements(read[rel], source, client)
        questions += data["stats"]["group_questions"]
        el_path = out / "elements" / f"elements.{pdf.stem}.json"
        el_path.parent.mkdir(parents=True, exist_ok=True)
        el_path.write_text(dumps(data), encoding="utf-8")
        print(
            f"  {rel}: {data['stats']['elements']} elements ({data['stats']['with_facts']} with data)",
            flush=True,
        )
        elements[rel] = data
    t = _timed(f"group ({questions} model questions)", t)
    plan = [e for d in elements.values() if d["source"] == "plan" for e in d["elements"]]
    shop = [e for d in elements.values() if d["source"] == "shop" for e in d["elements"]]
    t = time.time()
    res = A.assign(plan, shop, client)
    (out / "assignment.json").write_text(
        dumps({"summary": A.summary(res), "pairs": res.pairs}), encoding="utf-8"
    )
    t = _timed(f"assign {A.summary(res)}", t)
    findings = C.build_findings(plan, shop, res, client)
    (out / "findings.json").write_text(dumps(findings), encoding="utf-8")
    t = _timed(f"compare {findings['counts']}", t)
    explainer = Explainer(client)
    explainer.prefetch(findings)
    t = _timed(f"explain ({explainer.calls} questions)", t)
    build_project_report(findings, out / "findings.pdf", explainer, project=project.name)
    _timed("report (1 pdf)", t)
    print(f"total {time.time() - t0:.1f}s", flush=True)
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--llm", choices=["auto", "server", "llama", "fake", "none"], default="auto")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--files", default=None, help="comma separated substrings of file paths")
    ap.add_argument("--gpu-layers", type=int, default=24)
    ap.add_argument(
        "--workers", type=int, default=6, help="processes for page extraction (OCR stays in one)"
    )
    args = ap.parse_args()
    pages = {int(p) for p in args.pages.split(",")} if args.pages else None
    files = set(args.files.split(",")) if args.files else None
    run(
        args.project,
        args.out,
        llm=args.llm,
        ocr=not args.no_ocr,
        force=args.force,
        pages=pages,
        files=files,
        gpu_layers=args.gpu_layers,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
