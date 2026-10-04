# Extraction lane: what the comparison lane receives

This note describes the metadata folder written by `python -m l2c.extract` and how to read its
quality signals. It contains no project data.

## Files (contract version 0.1.0)

`manifest.json`, `elements.json` (Appendix A form), `elements.ext.json` (adds `match_key`, `grid`,
`level`, `quality`, `bbox`, `raw_text`, `provenance`), `grid.json`, `levels.json`, `sheets.json`,
`ids.json`. Load with `l2c.contract.io.read_bundle`; a version mismatch raises.

## Which pages were read and how (`sheets.json`, field `layout`)

| layout | meaning |
|---|---|
| `plan_outline` | column plan with a grid; blocks bound to column outlines |
| `plan_blocks_without_grid` | blocks found, no grid: elements are unbound (needs review) |
| `shop_label_strip` | shop elevation sheet: one strip per grid label, levels from elevation lines |
| `shop_schedule_table` | shop schedule table: each table column lists grid cells plus bars and ties |
| `needs_ocr` | no text layer; run with `--ocr` |
| `not_a_column_plan`, `no_column_blocks`, `type_not_supported:<type>` | not covered, with the reason |
| `error:<ExceptionName>`, `error:open_failed:<ExceptionName>` | the page or file failed; the run went on |

A page is never guessed. If a layout is not recognised it is reported, not extracted.

## Quality signals worth using

- `quality.overall` is the weakest link of type, level, location and every attribute, times
  `0.85 ** failed_checks`. Elements at 0.7 or more can carry a firm verdict; below that they should
  be needs-review.
- `quality.flags` explains low scores. Frequent ones: `weak_binding` (thin margin to the runner-up
  outline, informational), `ambiguous_cell`, `unbound_block`, `second_pass_binding`,
  `below_lowest_level` (foundation dowel segment, level `FDN`), `spacing_not_on_sheet` (ties without
  a printed spacing: not a defect), `cell_count_mismatch` (a schedule column lists a different
  number of cells than its printed multiplier), `label_snapped` and `ocr_snapped` (a character was
  repaired), `ocr_text` (read by OCR; confidence is folded into the score).
- Off-grid columns are bound with a relaxed snap and a grid confidence of at most 0.6, so they never
  reach a firm verdict on their own.
- Schedule sheets give every listed cell the table column's reinforcement. `armature[0]` is the
  vertical bars (`quantite` = bars per column), `armature[1]` the ties (`quantite` = ties per
  column, `espacement_mm`). Bare spacings of 30 or more are millimetres, smaller ones inches.

## Estimating binding accuracy without labels

`python scripts/binding_witness.py <metadata_dir>` compares plan columns that differ from their
sheet's usual profile with the shop element at the same grid cell. The atypical agreement is a lower
bound (genuine plan/shop differences count as disagreement) and is reported next to the chance
level. A change to binding must not lower it.

## Running

```
python -m l2c.extract <project_dir> --out data/out/<project>/metadata [--ocr] [--config c.json]
python scripts/probe_project.py <project_dir>       # what is covered and why not
python scripts/validate_extract.py <project_dir>    # thresholds on parsed and bound shares
```
