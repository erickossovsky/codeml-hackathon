# Lean pipeline: plans and shop drawings to one findings report

Status: working prototype on branch `dev`. Code: `backend/l2c/pipeline/`, `backend/l2c/llm/`, `backend/l2c/free/`.

## What it does

One command takes a project folder (plan PDFs at the top, shop drawings under `DA/`) and writes:

- `elements/elements.<file>.json`: one free-form element list per PDF (English keys; Appendix A of the challenge is a reference, not an export target);
- `assignment.json` and `findings.json`: plan-to-shop pairs and one finding per real-world element (compliant, non-compliant, to verify, missing from the shop drawings, added in the shop drawings);
- `findings.pdf`: one report for the project, per plan sheet, with page and X, Y on both documents for every discrepancy.

```
python -m l2c.pipeline <project_dir> --out data/out/<project> [--workers 6] [--no-ocr] [--llm server|llama|fake]
python -m l2c.pipeline.evaluate <project_dir> --out data/out/eval_<project> [--mutations 30] [--seed 1]
```

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

`l2c.pipeline.evaluate` plants single-number changes (bar count, bar size or spacing) in shop notes whose pair agreed before, runs the pipeline again and reports how many come back, why each miss was missed, how many false flags the changes caused, and the flags on the unchanged project (background). It works on any project, so changes are judged on several projects rather than tuned to one set of known cases.

## Known limits

- Elements that the shop states as several dowel groups under a cross-reference to a plan elevation are not yet summed and linked.
- About half of the plan's reinforcement notes find no shop counterpart; many are legitimately not covered by the shop drawings, some are pairing gaps.
- Scanned projects are bound by OCR time (about 6 s per large page on the GPU).
- Precision: the unchanged development projects still produce false non-conformities beyond the real ones.
