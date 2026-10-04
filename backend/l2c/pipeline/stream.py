"""Streaming run: each file's metadata as soon as that file is read, findings that grow while the
rest
of the project is still loading, and the final result when everything is in.

python -m l2c.pipeline.stream <project_dir> --out <dir> [--llm auto|server|none] [--workers 6]
    [--ocr-gpu N] [--ocr-cpu N] [--partial-every 45] [--no-cache] [--no-file-cache]

Written under --out while it runs:
- progress.json: every file (pages, pages needing OCR, status, seconds) and the event list, in the
  step/status/detail shape the UI already polls;
- elements/elements.<file>.json: the free-form elements of one file, the moment it is read;
- findings.partial.json and findings.partial.pdf: matching and comparison of what is read so far,
  refreshed while files arrive (no model questions: deterministic and a few seconds each);
- findings.json, findings.pdf, assignment.json: the final result.

Plans are read first (nothing can be compared before them), then shop files with the fewest pages
needing OCR. Text pages go through a process pool; image-only pages through OCR workers that share
one queue (GPU and CPU workers together), and each OCR page joins the pool the moment it is read.
"""

from __future__ import annotations

import argparse
import json
import pickle
import tempfile
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path, PurePath

import pymupdf

from l2c.contract.io import dumps
from l2c.extract.config import DEFAULT_CONFIG
from l2c.ingest.ocr import cache_key, cached_ocr_page
from l2c.llm.client import NeutralClient, make_client
from l2c.pipeline import assign as A
from l2c.pipeline import compare as C
from l2c.pipeline import lean, pageread
from l2c.pipeline.__main__ import OCR_CACHE, discover
from l2c.pipeline.filecache import FileCache, relocate, replace_retry, sha256_file
from l2c.pipeline.report import Explainer, build_project_report

FILE_CACHE = OCR_CACHE.parent / "files"  # what each PDF says, by content (see filecache)


class Progress:
    """progress.json, rewritten on every change so a UI or a person can follow the run."""

    def __init__(self, path: Path, t0: float) -> None:
        self.path, self.t0 = path, t0
        self.files: dict[str, dict] = {}
        self.events: list[dict] = []

    def event(self, step: str, status: str, detail: str = "") -> None:
        t = round(time.time() - self.t0, 1)
        self.events.append(
            {"kind": "step", "step": step, "status": status, "detail": detail, "t": t}
        )
        print(f"[{t:6.1f}s] {step} {status} {detail}", flush=True)
        self.save()

    def save(self) -> None:
        state = {
            "seconds": round(time.time() - self.t0, 1),
            "files": list(self.files.values()),
            "events": self.events,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
        replace_retry(tmp, self.path)


def _needs_ocr(page: pymupdf.Page) -> bool:
    return (
        pageread.word_count(page) < lean.MIN_WORDS
        or pageread.raster_share(page) >= pageread.RASTER_SHARE_MIN
    )


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dumps(data), encoding="utf-8")
    replace_retry(tmp, path)


def _counts(c: dict) -> str:
    n, u, ok = c.get("differs", 0), c.get("uncertain", 0), c.get("conforms", 0)
    return f"{n} non-compliant, {u} to verify, {ok} compliant"


def _sides(files: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    plan = [e for d in files.values() if d["source"] == "plan" for e in d["elements"]]
    shop = [e for d in files.values() if d["source"] == "shop" for e in d["elements"]]
    return plan, shop


def run(
    project: Path,
    out: Path,
    *,
    llm: str = "auto",
    workers: int = 6,
    ocr_gpu: int | None = None,
    ocr_cpu: int | None = None,
    partial_every: float = 45.0,
    ocr_cache: Path | None = OCR_CACHE,
    file_cache: Path | None = FILE_CACHE,
) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    (out / "elements").mkdir(exist_ok=True)
    prog = Progress(out / "progress.json", t0)
    config = DEFAULT_CONFIG
    found = discover(project)
    cache = FileCache(file_cache) if file_cache else None
    files: dict[str, dict] = {}
    scan: dict[str, dict] = {}
    for pdf, rel, source in found:
        digest = sha256_file(pdf)
        state = cache.status(rel, digest, source) if cache else "new"
        if state == "cached":
            entry = cache.get(digest, source)
            files[rel] = relocate(entry["elements"], rel)
            scan[rel] = {
                "pdf": pdf,
                "source": source,
                "pages": entry["pages"],
                "ocr": [],
                "size": entry["size"],
            }
            scan[rel].update(digest=digest, state=state, ocr_pages=entry["ocr_pages"])
            continue
        with pymupdf.open(pdf) as doc:
            scan[rel] = {
                "pdf": pdf,
                "source": source,
                "pages": len(doc),
                "ocr": [i for i in range(len(doc)) if _needs_ocr(doc[i])],
                "size": pdf.stat().st_size,
            }
        scan[rel].update(digest=digest, state=state, ocr_pages=len(scan[rel]["ocr"]))
    order = sorted(found, key=lambda f: (f[2] != "plan", len(scan[f[1]]["ocr"]), f[1]))
    for _, rel, source in order:
        prog.files[rel] = {
            "file": rel,
            "source": source,
            "pages": scan[rel]["pages"],
            "ocr_pages": scan[rel]["ocr_pages"],
            "status": "waiting",
            "cache": scan[rel]["state"],
        }
    n_ocr = sum(len(s["ocr"]) for s in scan.values())
    n_shop = sum(1 for f in found if f[2] == "shop")
    prog.event(
        "ingest",
        "done",
        f"{len(found) - n_shop} plan file(s), {n_shop} shop files, "
        f"{sum(s['pages'] for s in scan.values())} pages, {n_ocr} need OCR; "
        + ", ".join(f"{n} {k}" for k, n in Counter(s["state"] for s in scan.values()).items()),
    )
    for _, rel, source in order:
        if scan[rel]["state"] == "cached":
            n = files[rel]["stats"]["elements"]
            prog.files[rel].update(status="read", elements=n, seconds=0.0)
            step = "extract_plan" if source == "plan" else "extract_shop"
            prog.event(step, "file", f"{rel}: {n} elements (already read, from the cache)")
            _write(out / "elements" / f"elements.{scan[rel]['pdf'].stem}.json", files[rel])

    scratch = None
    if ocr_cache is None:
        scratch = tempfile.TemporaryDirectory()
        ocr_cache = Path(scratch.name)
    jobs = [(scan[rel]["pdf"], i + 1) for _, rel, _ in order for i in scan[rel]["ocr"]]
    procs = []
    if jobs:
        from l2c.ingest.ocr_workers import default_mix, start_workers

        auto_gpu, auto_cpu = default_mix()
        ocr_gpu = auto_gpu if ocr_gpu is None else ocr_gpu
        ocr_cpu = auto_cpu if ocr_cpu is None else ocr_cpu
        procs = start_workers(jobs, config, ocr_cache, gpu_workers=ocr_gpu, cpu_workers=ocr_cpu)
        prog.event("ocr", "active", f"{len(jobs)} pages, {ocr_gpu} GPU and {ocr_cpu} CPU workers")

    pool = ProcessPoolExecutor(workers)
    futures: dict = {}
    pending_ocr: list[tuple[str, int]] = []
    for _, rel, _ in order:
        for i in range(scan[rel]["pages"]):
            if i in scan[rel]["ocr"]:
                pending_ocr.append((rel, i))
            else:
                futures[pool.submit(lean._page_task, (scan[rel]["pdf"], rel, i, None, config))] = (
                    rel,
                    i,
                )
    got: dict[str, dict[int, dict]] = {rel: {} for rel in scan}
    reads: dict[str, dict] = {}
    neutral = NeutralClient()
    # files from the cache are in already: the first partial findings need not wait for a new one
    dirty = any(d["source"] == "shop" for d in files.values())
    last_partial, ocr_done_at = 0.0, None

    def file_done(rel: str) -> None:
        results = [got[rel][i] for i in sorted(got[rel])]
        read = {
            "file": {
                "file": rel,
                "stem": PurePath(rel).stem,
                "pages": scan[rel]["pages"],
                "size_bytes": scan[rel]["size"],
            },
            "pages": [r["summary"] for r in results],
            "blocks": [b for r in results for b in r["blocks"]],
        }
        data = lean.build_elements(read, scan[rel]["source"], neutral)
        reads[rel], files[rel] = read, data
        if cache:
            meta = {k: scan[rel][k] for k in ("pages", "ocr_pages", "size")}
            cache.put(scan[rel]["digest"], scan[rel]["source"], rel, meta, data)
        _write(out / "elements" / f"elements.{scan[rel]['pdf'].stem}.json", data)
        prog.files[rel].update(
            status="read", elements=data["stats"]["elements"], seconds=round(time.time() - t0, 1)
        )
        step = "extract_plan" if scan[rel]["source"] == "plan" else "extract_shop"
        prog.event(
            step,
            "file",
            f"{rel}: {data['stats']['elements']} elements ({len(files)}/{len(found)} files)",
        )

    def partial() -> None:
        plan, shop = _sides(files)
        res = A.assign(plan, shop, neutral)
        findings = C.build_findings(plan, shop, res, neutral)
        k = sum(1 for d in files.values() if d["source"] == "shop")
        secs = time.time() - t0
        findings["partial"] = {
            "shop_files_read": k,
            "shop_files": n_shop,
            "seconds": round(secs, 1),
        }
        _write(out / "findings.partial.json", findings)
        banner = (
            f"Partial result after {secs:.0f} s: {k} of {n_shop} shop files read so far. "
            "Matching without model questions; the final report replaces this one."
        )
        build_project_report(
            findings,
            out / "findings.partial.pdf",
            Explainer(None),
            project=project.name,
            banner=banner,
        )
        c = findings["counts"]
        prog.event(
            "compare",
            "partial",
            f"{k}/{n_shop} shop files: {_counts(c)}",
        )

    while len(files) < len(found):
        still = []
        for rel, i in pending_ocr:
            entry = ocr_cache / f"{cache_key(scan[rel]['pdf'], i + 1, config)}.pkl"
            words = None
            if entry.is_file():
                try:
                    words = pickle.loads(entry.read_bytes()).words
                except Exception:
                    words = None  # being written: next round
            if words is None:
                still.append((rel, i))
            else:
                futures[pool.submit(lean._page_task, (scan[rel]["pdf"], rel, i, words, config))] = (
                    rel,
                    i,
                )
        pending_ocr = still
        if not pending_ocr and procs and ocr_done_at is None:
            ocr_done_at = time.time()
            prog.event("ocr", "done", f"{len(jobs)} pages in {ocr_done_at - t0:.0f} s")
        if pending_ocr and procs and all(p.poll() is not None for p in procs):
            rel, i = pending_ocr.pop(0)  # the workers stopped early: read what is left here
            words = cached_ocr_page(scan[rel]["pdf"], i + 1, config, ocr_cache).words
            futures[pool.submit(lean._page_task, (scan[rel]["pdf"], rel, i, words, config))] = (
                rel,
                i,
            )
        if futures:
            done, _ = wait(list(futures), timeout=0.5, return_when=FIRST_COMPLETED)
        else:
            done = set()
            time.sleep(0.5)
        for fu in done:
            rel, i = futures.pop(fu)
            got[rel][i] = fu.result()[2]
            if len(got[rel]) == scan[rel]["pages"]:
                file_done(rel)
                dirty = True
        plans_in = all(rel in files for _, rel, s in found if s == "plan")
        if (
            dirty
            and plans_in
            and any(d["source"] == "shop" for d in files.values())
            and len(files) < len(found)
            and time.time() - last_partial >= partial_every
        ):
            partial()
            last_partial, dirty = time.time(), False
    pool.shutdown()
    for p in procs:
        p.wait()
    if scratch is not None:
        scratch.cleanup()

    # final pass: the model (when one is used) for the close calls, then the report
    client = make_client(llm)
    prog.event("compare", "active", f"final pass, model: {client.model_id}")
    if not isinstance(client, NeutralClient):
        for _, rel, source in order:
            if rel not in reads:
                continue  # from the cache: grouped when it was first read
            files[rel] = lean.build_elements(reads[rel], source, client)
            _write(out / "elements" / f"elements.{scan[rel]['pdf'].stem}.json", files[rel])
    plan, shop = _sides(files)
    res = A.assign(plan, shop, client)
    _write(out / "assignment.json", {"summary": A.summary(res), "pairs": res.pairs})
    findings = C.build_findings(plan, shop, res, client)
    _write(out / "findings.json", findings)
    c = findings["counts"]
    prog.event(
        "compare",
        "done",
        _counts(c),
    )
    explainer = Explainer(None if isinstance(client, NeutralClient) else client)
    explainer.prefetch(findings)
    build_project_report(findings, out / "findings.pdf", explainer, project=project.name)
    prog.event("report", "done", f"findings.pdf, total {time.time() - t0:.0f} s")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--llm", choices=["auto", "server", "llama", "fake", "none"], default="auto")
    ap.add_argument("--workers", type=int, default=6, help="processes for reading text pages")
    ap.add_argument(
        "--ocr-gpu", type=int, default=None, help="OCR workers on the GPU (default: auto)"
    )
    ap.add_argument(
        "--ocr-cpu", type=int, default=None, help="OCR workers on the CPU (default: auto)"
    )
    ap.add_argument(
        "--partial-every",
        type=float,
        default=45.0,
        help="seconds between partial findings while files arrive",
    )
    ap.add_argument(
        "--no-cache", action="store_true", help="keep OCR results in a temporary folder only"
    )
    ap.add_argument(
        "--no-file-cache", action="store_true", help="read every file even if it was read before"
    )
    args = ap.parse_args()
    run(
        args.project,
        args.out,
        llm=args.llm,
        workers=args.workers,
        ocr_gpu=args.ocr_gpu,
        ocr_cpu=args.ocr_cpu,
        partial_every=args.partial_every,
        ocr_cache=None if args.no_cache else OCR_CACHE,
        file_cache=None if args.no_file_cache else FILE_CACHE,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
