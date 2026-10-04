# L2C: From Plans to Shop Drawings

Checks reinforcement shop drawings against structural plans. The PDFs of a project go in; a JSON
database of every element found (free-form, with sheet, page and X, Y), the findings, and one PDF
report per project organised by plan sheet come out. Everything runs locally and offline;
confidential drawings never leave the machine.

## Entry points

| What | Command |
|---|---|
| Web app (upload, live progress, findings while loading, drawing viewer) | `cd backend && uvicorn l2c.api:app --port 8000`, then `cd frontend && npm install && npm run dev` (http://localhost:5173) |
| Command line, one project | `python -m l2c.pipeline.stream <project_dir> --out data/out/<project>` |
| Same flow through the API | `python scripts/api_run.py <project_dir>` |
| Demonstration notebook | `pipeline_demo.ipynb` (set `PROJECT` or `L2C_PROJECT`) |
| Planted-change evaluation | `python -m l2c.pipeline.evaluate <project_dir> --out data/out/eval_<project>` |

Example outputs on a made-up project (the real projects' outputs hold drawing data and are handed in
separately): `shared/fixtures/mock_outputs/`, regenerated with `python scripts/make_mock_outputs.py`.

`<project_dir>` holds the plan PDF(s) at its top and the shop drawings anywhere under a `DA/`
folder. The command line and the API write, under the output folder: `elements/elements.<file>.json`
(one per PDF, as soon as it is read), `findings.partial.json` / `.pdf` while files are still loading,
then `findings.json`, `assignment.json` and `findings.pdf`, plus `progress.json`.

## Setup (macOS, Linux, Windows)

```
uv venv --python 3.12 .venv
# macOS/Linux: source .venv/bin/activate      Windows: .venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
uv pip install -e .
python scripts/install_hooks.py      # enables the data/secret guard on every commit
python scripts/check.py              # lint + format + tests + guard
cd frontend && npm install           # the web app (Node 20 or later)
```

Optional, all local and git-ignored under `data/` (see `docs/lean-pipeline.md`): OCR on the GPU
(`onnxruntime-gpu` for CUDA 12 in `data/vendor/ortgpu`), and the local model for close calls
(`llama-server` from llama.cpp in `data/bin/llama`, Qwen3-4B-Instruct-2507 GGUF in `data/models`,
`requirements/llm.txt`). Without them OCR runs on the CPU and the pipeline runs without model
questions (`--llm none`, the default of the web app). No model is trained; RapidOCR (PP-OCR) and
Qwen3 are used as published (Apache 2.0).

## Architecture

```
PDFs ─► read ─► group ─► match ─► compare ─► report
        │        │        │        │          └─ one PDF per project, by plan sheet
        │        │        │        └─ bar groups paired by what agrees; units normalised
        │        │        └─ grid cell, level, kind, content; Hungarian assignment
        │        └─ words into notes and free-form elements (kind, grid cell, level, bars, facts)
        └─ text and positions (PyMuPDF); OCR for scanned pages (RapidOCR workers)
```

- `backend/l2c/pipeline/stream.py`: the streaming run (plans first; text pages in a process pool,
  scanned pages through OCR workers sharing one queue; partial findings while files arrive).
- `backend/l2c/pipeline/lean.py`, `backend/l2c/free/`: reading and grouping into free-form elements.
- `backend/l2c/pipeline/assign.py`, `compare.py`: matching and comparison; `report.py`: the PDF.
- `backend/l2c/pipeline/filecache.py`: what each PDF says, cached by content in `data/cache/files`,
  so a file already read is not read again and a changed one is.
- `backend/l2c/api.py`: the web API; `frontend/`: the React app.
- `backend/l2c/llm/`: the local model client (optional).

Details, measurements and choices: `docs/lean-pipeline.md`.

## Assumptions

- Plans are the PDFs at the top of a project folder; shop drawings are under `DA/`.
- Members are located by the structural grid (lettered rows, numbered columns) and the level; a note
  sits next to the member it describes, and the same member on two documents shares cell and level.
- Reinforcement is written as notes (count, size such as `20M`, spacing, mark); imperial and metric
  values are compared after conversion (equal within 4%).
- Shop drawings do not cover every plan element: an unmatched plan element is listed as missing for
  information, not counted as an error.
- The engineer decides: anything uncertain is listed to verify, never passed as compliant.

## Known limitations

- Scanned projects are bound by OCR time: about 8 to 10 s per 36 x 24 in sheet on a 4 GB laptop GPU
  (a project with 140 scanned sheets takes about 20 minutes the first time; seconds from the cache).
- On scanned projects, grid labels read by OCR often differ from the plan's grid names, so many
  elements stay unpaired; text-layer projects pair far better.
- A difference counts as a non-conformity only when the rest of its bar group agrees; otherwise it
  is listed to verify. The same difference at three or more places is reported once, as systematic.
- Elements stated as several dowel groups under a cross-reference to an elevation are not summed.
- On the development project the planted-change evaluation finds about 80% of single-number changes.

## Earlier flow (deterministic extraction to the shared contract)

```
python scripts/run_flow.py <project_dir> [--ocr]     # the whole flow in one command
python -m l2c.extract <project_dir> --out data/out/<project>/metadata [--ocr] [--workers N]
python -m l2c.compare data/out/<project>/metadata --out data/out/<project>/compare [--ml]
```

## Lanes

- `backend/l2c/{ingest,extract}`: PDF to metadata (Eric). Deterministic rules; OCR only for pages
  without a text layer.
- `backend/l2c/{pipeline,free,llm}`, `backend/l2c/api.py`: the streaming pipeline, matching,
  comparison, report and web API (Ian).
- `backend/l2c/{match,compare,report,mock}`: the earlier comparison lane.
- `backend/l2c/contract`, `shared/`: the contract between the lanes (both; contract PRs only).
- `frontend/`: the web app.

## Data rules

Real drawings and everything derived from them live under `data/`, `deliverables/` or `demo/`
(git-ignored). `python scripts/purge.py --yes` removes them at the end of the event.
