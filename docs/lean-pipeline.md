# Lean pipeline: plans and shop drawings to one findings report

Status: working prototype on branch `dev`. Code: `backend/l2c/pipeline/`, `backend/l2c/llm/`, `backend/l2c/free/`.

## What it does

One command takes a project folder (plan PDFs at the top, shop drawings under `DA/`) and writes:

- `elements/elements.<file>.json`: one free-form element list per PDF (English keys; Appendix A of the challenge is a reference, not an export target);
- `assignment.json` and `findings.json`: plan-to-shop pairs and one finding per real-world element (compliant, non-compliant, to verify, missing from the shop drawings, added in the shop drawings);
- `findings.pdf`: one report for the project, per plan sheet, with page and X, Y on both documents for every discrepancy.

```
python -m l2c.pipeline <project_dir> --out data/out/<project> [--workers 6] [--no-ocr] [--llm server|llama|fake|none]
python -m l2c.pipeline.stream <project_dir> --out data/out/<project> [--llm none] [--ocr-gpu 2] [--ocr-cpu 4] [--partial-every 45] [--no-cache]
python -m l2c.pipeline.evaluate <project_dir> --out data/out/eval_<project> [--mutations 30] [--seed 1] [--llm none]
```

## Streaming run

`l2c.pipeline.stream` gives results while the project is still loading:

- `progress.json`: every file (pages, pages needing OCR, status) and the events so far, in the step/status/detail shape the UI polls;
- `elements/elements.<file>.json`: written the moment that file is read;
- `findings.partial.json` and `findings.partial.pdf`: matching and comparison of what is read so far, refreshed every `--partial-every` seconds, without model questions;
- `findings.json`, `findings.pdf`: the final result.

Plans are read first, then shop files with the fewest image-only pages. Text pages go through a process pool. Image-only pages go to OCR workers (separate processes: one on the GPU at above-normal priority, the rest on the CPU with one thread each at below-normal priority) that share one queue through claim files, and each page joins the pool as soon as it is read.

OCR notes, measured on 36 x 24 in scanned sheets at 200 dpi:

- One GPU worker reads a page in about 7 s. A 4 GB card holds one OCR session; a second one ran out of memory.
- RapidOCR 1.4.4 copies its global thread settings over the per-model ones, so the thread limit has to be the global `intra_op_num_threads` / `inter_op_num_threads`; otherwise every CPU worker takes all cores and starves the GPU worker.
- Cheaper settings lose notation: detection at 0.67x scale kept 76% of the bar notation tokens, without the angle classifier 60%. Both stay at full setting. A larger recognition batch changed readings, so it stays at 6; the angle classifier batch (fixed input size) is 64.

## Web app

`backend/l2c/api.py` (FastAPI) is what the UI in `frontend/` talks to. `POST /api/run` stores the uploaded PDFs in `data/runs/<id>/input` (plans at the top, shop drawings under `DA/`) and starts `l2c.pipeline.stream` as its own process. A watcher turns `progress.json` into the UI's events: `step` (ingest, extract_plan, extract_shop, compare, report), `note` (one file read, OCR progress), `partial` (findings so far, in the UI's `RunResult` shape) and `result`. `GET /api/findings/<id>`, `/api/elements/<id>[/<file>]` and `/api/report/<id>` serve the latest outputs at any time. `L2C_LLM` sets the model mode of the final pass (default `none`). `scripts/api_run.py <project>` drives the same flow from a terminal.

## Stages

| Stage | What | Who |
|---|---|---|
| Read | Text and its position, one pass per page, in a process pool. OCR only for pages with no text layer or mostly raster, in the main process, cached on disk, on the GPU when available. | code |
| Group | Words into lines and notes. Strip charts (a grid label at the foot of each strip), cells named in a note's own text, schedules keyed by a type code (`TYPE x`) and the lone tags that point at them, detail titles. | code; the model for notes that sit between two candidates |
| Match | Candidates by grid cell and the cells a note sits between, level, kind and content; Hungarian assignment per connected component with an "unmatched" option. A second pass looks about one bay around a note for a shop note that says nearly the same thing. | code; the model for close calls, one pair per question |
| Compare | All the notes of a member on each side are compared together. Units are normalised (6" equals 152.4 mm). A difference counts only when the rest of the bar group or member agrees (evidence weight); otherwise it is a possible difference for review. Only reinforcement values are flagged. | code; the model for leftover properties |
| Report | One PDF, per plan sheet; one short sentence per distinct difference. | code layout; the model writes sentences |

## Local model

`llama-server` (llama.cpp, open source) on 127.0.0.1 with Qwen3-4B-Instruct-2507 (Apache 2.0), fully on the GPU, 8 parallel slots. Answers are constrained to an option list; the certainty is the model's own probability. Every question holds one or two compact elements. Nothing leaves the machine.

Setup (files are git-ignored, under `data/`):

- `data/bin/llama/`: the llama.cpp release for Windows CUDA 12.4 (`llama-b*-bin-win-cuda-12.4-x64.zip` plus `cudart-llama-bin-win-cuda-12.4-x64.zip`).
- `data/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf` from Hugging Face.
- Optional GPU OCR: `onnxruntime-gpu==1.22.0` and `nvidia-cudnn-cu12` installed with `pip install --target` into `data/vendor/ortgpu` and `data/vendor/ortgpu_cudnn`; set `L2C_OCR_GPU=0` to force the CPU.

The pipeline starts the server itself after reading (the OCR engine releases the GPU first).

## Measuring without an answer key

`l2c.pipeline.evaluate` plants single-number changes (bar count, bar size or spacing) in shop notes whose pair agreed before, runs the pipeline again and reports how many come back, why each miss was missed, how many false flags the changes caused, and the flags on the unchanged project (background). It works on any project, so changes are judged on several projects rather than tuned to one set of known cases. The changed run is saved too (`findings.changed.json`), so each miss can be traced to its pairing.

What it taught us:

- A member printed on several shop sheets is several statements. Merging them hid a changed copy behind an unchanged one; a line that restates another note's line (one word apart) or names the same role (vertical bars, ties) is now compared with the same plan line.
- Two identical bar groups in one note (long and transverse bars) are two groups, and identical agreements count once as evidence.
- Bar groups are paired by everything that agrees (an optimal assignment), not greedily by size.
- Two known, different storeys are never paired: bars change between storeys, so such a pair reads as a changed value. Foundation elements are exempt (their level label is not evidence).
- Spacing and section are equal within 4% (inch values against rounded metric ones).
- The same difference at three or more places becomes one systematic finding for review, listing every place.

The evaluator only plants changes after reading and only in pairs that already agree, so it cannot see OCR misreads or wrong pairings; those need their own negatives.

## Known limits

- Elements that the shop states as several dowel groups under a cross-reference to a plan elevation are not yet summed and linked.
- About half of the plan's reinforcement notes find no shop counterpart; many are legitimately not covered by the shop drawings, some are pairing gaps.
- Scanned projects are bound by OCR time: about 7 s per 36 x 24 in page for one GPU worker at 200 dpi (detection about 3 s, angle classifier about 1 s, recognition about 3 s), on a 4 GB laptop GPU that holds two OCR workers.
- Model questions: on CLP, matching without them found the same known cases with slightly fewer flags, in 18 s instead of about 2 minutes. `--llm none` runs without the model.
- Precision: the unchanged development projects still produce false non-conformities beyond the real ones.
