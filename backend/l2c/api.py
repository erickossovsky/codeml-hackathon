"""Local web API for the UI: upload a project, follow it while it loads, get the results.

POST /api/run                    plans[] and shops[] (PDF files) -> {"runId": id}
GET  /api/status/{id}            progress events since the last poll (the UI's ProgressEvent shape)
GET  /api/findings/{id}          the latest findings in the UI's shape (partial while loading)
GET  /api/elements/{id}          the per-file metadata written so far
GET  /api/elements/{id}/{name}   one file's elements (free-form JSON)
GET  /api/pdf/{id}/{name}        an uploaded PDF of the run (for the viewer)
GET  /api/report/{id}            findings.pdf, or the partial report until the final one exists

Run from backend/:  uvicorn l2c.api:app --port 8000

Each run is a folder under data/runs/<id> (git-ignored, removed by scripts/purge.py): the uploaded
plans in input/, the shop drawings in input/DA/, the outputs in out/. The pipeline runs as its own
process (python -m l2c.pipeline.stream) and a watcher thread turns its progress.json into events.
L2C_LLM picks the model mode of the final pass (default `none`: no model questions).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from l2c.pipeline.envelope import run_result

REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / "data" / "runs"
LLM = os.environ.get("L2C_LLM", "none")

app = FastAPI(title="L2C plan and shop drawing check")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@dataclass
class Run:
    dir: Path
    plans: list[str]
    shops: list[str]
    events: list[dict] = field(default_factory=list)
    sent: int = 0
    latest: dict | None = None  # the latest findings in the UI's shape

    @property
    def project(self) -> str:
        return PurePath(self.plans[0]).stem if self.plans else "project"


runs: dict[str, Run] = {}


def _save(files: list[UploadFile], folder: Path) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for f in files:
        name = PurePath(f.filename or "file.pdf").name
        if name in names:
            name = f"{len(names)}_{name}"
        (folder / name).write_bytes(f.file.read())
        names.append(name)
    return names


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # not written yet, or being replaced


def _elements(prog: dict, source: str) -> int:
    return sum(
        f.get("elements", 0)
        for f in prog["files"]
        if f["source"] == source and f["status"] == "read"
    )


def _translate(e: dict, prog: dict, seen: set[str]) -> list[dict]:
    """One pipeline event as UI events. Steps open once and close once; per-file progress is a
    note."""
    step, status, detail = e["step"], e["status"], e.get("detail", "")
    files = prog["files"]
    out: list[dict] = []

    def open_(s: str) -> None:
        if s not in seen:
            seen.add(s)
            out.append({"kind": "step", "step": s, "status": "active"})

    if step == "ingest":
        out.append({"kind": "step", "step": "ingest", "status": "done", "detail": detail})
        open_("extract_plan")
    elif step == "ocr":
        open_("extract_shop")
        out.append({"kind": "note", "step": "extract_shop", "text": f"OCR {status}: {detail}"})
    elif step in ("extract_plan", "extract_shop"):
        source = "plan" if step == "extract_plan" else "shop"
        open_(step)
        total = sum(1 for f in files if f["source"] == source)
        read = sum(1 for f in files if f["source"] == source and f["status"] == "read")
        n = _elements(prog, source)
        out.append(
            {
                "kind": "note",
                "step": step,
                "text": detail,
                "detail": f"{n} elements · {read}/{total} files",
            }
        )
        if read == total:
            out.append({"kind": "step", "step": step, "status": "done", "detail": f"{n} elements"})
            if source == "plan":
                open_("extract_shop")
    elif step == "compare" and status == "partial":
        open_("compare")
        out.append({"kind": "note", "step": "compare", "text": f"Partial findings: {detail}"})
    elif step == "compare":
        if status == "active":
            open_("compare")
        else:
            out.append({"kind": "step", "step": "compare", "status": "done", "detail": detail})
            open_("report")
    elif step == "report":
        out.append({"kind": "step", "step": "report", "status": "done", "detail": detail})
    return out


def _watch(run_id: str, run: Run, proc: subprocess.Popen) -> None:
    out = run.dir / "out"
    seen_steps: set[str] = {"ingest"}
    n_events, partial_mtime = 0, None
    while True:
        alive = proc.poll() is None
        prog = _read_json(out / "progress.json")
        if prog:
            for e in prog["events"][n_events:]:
                run.events.extend(_translate(e, prog, seen_steps))
            n_events = len(prog["events"])
        pf = out / "findings.partial.json"
        if pf.is_file() and pf.stat().st_mtime != partial_mtime:
            partial_mtime = pf.stat().st_mtime
            f = _read_json(pf)
            if f:
                run.latest = run_result(f, run_id, run.project, run.plans, run.shops)
                run.events.append({"kind": "partial", "result": run.latest})
        if not alive:
            break
        time.sleep(0.5)
    final = _read_json(out / "findings.json")
    if proc.returncode == 0 and final:
        run.latest = run_result(final, run_id, run.project, run.plans, run.shops)
        run.events.append({"kind": "result", "result": run.latest})
    else:
        run.events.append(
            {
                "kind": "error",
                "message": f"The check stopped (exit {proc.returncode}); see {out / 'run.log'}",
            }
        )


@app.post("/api/run")
async def start_run(
    plans: Annotated[list[UploadFile], File()],
    shops: Annotated[list[UploadFile] | None, File()] = None,
):
    shops = shops or []
    run_id = uuid4().hex[:12]
    run_dir = RUNS / run_id
    run = Run(run_dir, _save(plans, run_dir / "input"), _save(shops, run_dir / "input" / "DA"))
    (run_dir / "out").mkdir(parents=True, exist_ok=True)
    run.events.append(
        {
            "kind": "step",
            "step": "ingest",
            "status": "active",
            "detail": f"{len(run.plans)} plans, {len(run.shops)} shop drawings",
        }
    )
    log = open(run_dir / "out" / "run.log", "w", encoding="utf-8")  # noqa: SIM115 - the process owns it
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "l2c.pipeline.stream",
            str(run_dir / "input"),
            "--out",
            str(run_dir / "out"),
            "--llm",
            LLM,
            "--no-cache",
        ],
        cwd=str(REPO / "backend"),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    runs[run_id] = run
    threading.Thread(target=_watch, args=(run_id, run, proc), daemon=True).start()
    return {"runId": run_id}


def _run(run_id: str) -> Run:
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return run


@app.get("/api/status/{run_id}")
async def get_status(run_id: str):
    run = _run(run_id)
    new = run.events[run.sent :]
    run.sent += len(new)
    return new


@app.get("/api/findings/{run_id}")
async def get_findings(run_id: str):
    run = _run(run_id)
    if run.latest is None:
        raise HTTPException(404, "no findings yet")
    return run.latest


@app.get("/api/elements/{run_id}")
async def list_elements(run_id: str):
    folder = _run(run_id).dir / "out" / "elements"
    return sorted(p.name for p in folder.glob("elements.*.json")) if folder.is_dir() else []


@app.get("/api/elements/{run_id}/{name}")
async def get_elements(run_id: str, name: str):
    path = _run(run_id).dir / "out" / "elements" / PurePath(name).name
    if not path.is_file():
        raise HTTPException(404, "not written yet")
    return FileResponse(path, media_type="application/json")


@app.get("/api/pdf/{run_id}/{name}")
async def get_pdf(run_id: str, name: str):
    """An uploaded PDF of a run, for the viewer (from the run folder, also after a restart)."""
    base = RUNS / PurePath(run_id).name / "input"
    for path in (base / PurePath(name).name, base / "DA" / PurePath(name).name):
        if path.is_file():
            return FileResponse(path, media_type="application/pdf")
    raise HTTPException(404, "no such file in this run")


@app.get("/api/report/{run_id}")
async def get_report(run_id: str):
    out = _run(run_id).dir / "out"
    for name in ("findings.pdf", "findings.partial.pdf"):
        if (out / name).is_file():
            return FileResponse(out / name, filename=f"{run_id}-{name}")
    raise HTTPException(404, "no report yet")
