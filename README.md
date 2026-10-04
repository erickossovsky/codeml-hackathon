# L2C: From Plans to Shop Drawings

Checks reinforcement shop drawings against structural plans. PDFs go in; a JSON metadata
database (Appendix A schema), per-shop-drawing comparison files and PDF reports come out.
Everything runs locally and offline; confidential drawings never leave the machine.

## Setup (macOS, Linux, Windows)

```
uv venv --python 3.12 .venv
# macOS/Linux: source .venv/bin/activate      Windows: .venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
uv pip install -e .
python scripts/install_hooks.py      # enables the data/secret guard on every commit
python scripts/check.py              # lint + format + tests + guard
```

## Run

```
python scripts/run_flow.py <project_dir> [--ocr]     # the whole flow in one command
python -m l2c.extract <project_dir> --out data/out/<project>/metadata [--ocr] [--workers N]
python -m l2c.compare data/out/<project>/metadata --out data/out/<project>/compare [--ml]
```

Use `--ocr` when the shop sheets have no text layer (about 10 to 40 s per page). Page reading runs in
parallel by default; OCR runs one page at a time.

`<project_dir>` holds the plan PDF(s) and a `DA/` folder of shop drawings. Both commands print
counts only, never drawing values.

## Lean pipeline (text, local model, one findings PDF)

```
python -m l2c.pipeline <project_dir> --out data/out/<project> [--workers 6]
python -m l2c.pipeline.evaluate <project_dir> --out data/out/eval_<project>   # planted-change recall
```

Reads text and positions (OCR where needed), groups notes, matches plan and shop elements with a
local open-source model for the close calls, and writes free-form element JSON, `findings.json` and
one `findings.pdf` per project. See `docs/lean-pipeline.md` for the stages, the model setup and the
known limits.

## Lanes

- `backend/l2c/{ingest,extract}`: PDF to metadata (Eric). Deterministic rules; OCR only for pages
  without a text layer.
- `backend/l2c/{match,compare,report,mock}`: metadata to comparison files and reports (Ian).
- `backend/l2c/contract`, `shared/`: the contract between the lanes (both; contract PRs only).

## Data rules

Real drawings and everything derived from them live under `data/`, `deliverables/` or `demo/`
(git-ignored). `python scripts/purge.py --yes` removes them at the end of the event.
