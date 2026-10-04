from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
import tempfile
from pathlib import Path
import os

from l2c.extract.__main__ import main as extract_main
from l2c.compare.run import run_comparison
from l2c.contract.io import read_bundle
from scripts.ui_fixture import envelope

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for run states
runs = {}
run_dirs = {}

def process_run(run_id: str, plan_files, shop_files):
    try:
        runs[run_id].append({"kind": "step", "step": "ingest", "status": "active"})
        
        # We don't use context manager so the directory persists for report downloads
        # In a real app we'd clean these up on a cron
        td = tempfile.mkdtemp()
        base_dir = Path(td)
        run_dirs[run_id] = base_dir
        
        plan_dir = base_dir / "plans"
        shop_dir = base_dir / "DA"
        plan_dir.mkdir()
        shop_dir.mkdir()
            
        for p, content in plan_files:
            (plan_dir / p).write_bytes(content)
        for s, content in shop_files:
            (shop_dir / s).write_bytes(content)
        
        runs[run_id].append({"kind": "step", "step": "ingest", "status": "done", "detail": f"{len(plan_files)} plans, {len(shop_files)} shops"})
        import subprocess
        runs[run_id].append({"kind": "step", "step": "extract_plan", "status": "active"})
        
        out_dir = base_dir / "out" / "metadata"
        out_dir.mkdir(parents=True)
        
        # Run extraction as a subprocess to mimic CLI usage
        subprocess.run([
            "python", "-m", "l2c.extract",
            str(base_dir),
            "--out", str(out_dir)
        ], check=True)
        
        runs[run_id].append({"kind": "step", "step": "extract_plan", "status": "done", "detail": "Extraction complete"})
        
        # The original frontend has extract_shop as a separate step, so we emit it too
        runs[run_id].append({"kind": "step", "step": "extract_shop", "status": "active"})
        runs[run_id].append({"kind": "step", "step": "extract_shop", "status": "done", "detail": "Extraction complete"})
        
        runs[run_id].append({"kind": "step", "step": "compare", "status": "active"})
        
        bundle = read_bundle(out_dir)
        findings = run_comparison(bundle)
        env = envelope(bundle, findings)
        
        runs[run_id].append({"kind": "step", "step": "compare", "status": "done", "detail": f"{env['stats']['matched']} matched"})
        
        runs[run_id].append({"kind": "step", "step": "report", "status": "active"})
        from l2c.report.pdf import write_summary
        write_summary(base_dir / "report.pdf", bundle.project, findings, [])
        
        runs[run_id].append({"kind": "step", "step": "report", "status": "done", "detail": "reports generated"})
        
        runs[run_id].append({"kind": "result", "result": env})

    except Exception as e:
        import traceback
        traceback.print_exc()
        runs[run_id].append({"kind": "error", "message": str(e)})


@app.get("/api/report/{run_id}")
async def get_report(run_id: str):
    from fastapi.responses import FileResponse
    # Find the tempdir associated with this run
    # For now we'll do a simple search or store the tempdir
    if run_id in run_dirs:
        return FileResponse(run_dirs[run_id] / "report.pdf", filename=f"{run_id}-report.pdf")
    return {"error": "not found"}

@app.post("/api/run")
async def start_run(background_tasks: BackgroundTasks, plans: list[UploadFile] = File(...), shops: list[UploadFile] = File(...)):
    run_id = str(uuid4())
    runs[run_id] = []
    
    # Read files in memory before handing off to background task
    plan_data = [(p.filename, await p.read()) for p in plans]
    shop_data = [(s.filename, await s.read()) for s in shops]
    
    background_tasks.add_task(process_run, run_id, plan_data, shop_data)
    
    return {"runId": run_id}

@app.get("/api/status/{run_id}")
async def get_status(run_id: str):
    if run_id not in runs:
        return []
    # In a real app we'd track an index so we don't return old events, 
    # but the frontend just processes them or ignores duplicates if we clear it.
    events = runs[run_id]
    runs[run_id] = [] # Clear so we only return new ones next poll
    return events
