# Comparison lane: MVP code review

Scope: Ian's lane (`match`, `compare`, `report`, `mock`, outputs, scripts). Eric's extraction code and the
Plan 00 stubs (`contract`, guard scripts) are out of scope except where noted.
Method: read every module, ran the suite, ran the CLI on the mock fixtures and on a real bundle, probed
edge cases. No drawing values appear in this document.

## Fixed in this pass

| # | Finding | Severity | Fix | Test |
|---|---|---|---|---|
| 1 | The same plan element appearing on several sheets (same level, row, column) paired once; the repeats became false `missing` findings (about 100 on the real bundle, more than half of all `missing`). | High | Matcher collapses repeats into one primary (best quality) and keeps the rest in `Pair.extra_plan`; conflicting repeats still surface through `self.duplicate`. | `test_matcher.py::test_duplicate_plan_elements_*` |
| 2 | `--ml` crashed with `ModuleNotFoundError` because the learned tier (plan task I9) is not built. | High | `add_pair_probabilities` falls back to rules only on `ImportError`; the CLI prints `ML tier not available` on stderr. | `test_outputs.py::test_cli_fails_cleanly_on_bad_input_and_on_the_unbuilt_ml_tier` |
| 3 | A wrong `contract_version`, a missing file or invalid JSON ended in a traceback. | Medium | CLI catches the error, prints `cannot read metadata: ...`, exits 2. | same test |
| 4 | `assign_to_shop_files` raised `KeyError` when a shop file had elements but no entry in `sheets.json`. | Medium | `setdefault`. | `test_outputs.py::test_assign_survives_*` |
| 5 | `read_bundle` rejected `str` paths. | Low | Accepts `Path | str`. | exercised by scripts |
| 6 | Dead code: unused `UNASSIGNED` constant, placeholder `performance_report.json`. | Low | Removed. | lint |

## Verified good

- `run_comparison` is pure and deterministic; finding ids are unique (2177/2177 on the real bundle).
- ML can only raise a no-difference pair to `needs_review`; verdicts are never lowered (`test_fusion.py`).
- Low-trust differences stay `needs_review`; no-difference pairs keep their trust as confidence.
- 60 random fuzz projects: every injected defect found, nothing else flagged, recall 1.0.
- Reports state `NOT COVERED` for every element type without data, even for an empty project.
- Outputs print counts only; real data stays under git-ignored `data/` (guard verified).

## Known limitations (deliberately not fixed in the MVP)

1. **Column profile is positional.** `profile()` reads `armature[0]` as vertical bars and `armature[1]` as ties. It
   works because the extractor writes them in that order; a different order silently mis-compares. The contract
   should carry a role (`repere` convention or an explicit field) before more element types are added.
2. **Systematic errors flood the report.** One wrong unit produced a finding per element (plausibility plus
   non_compliant). A project-level "systematic issue" finding that collapses a check failing on more than about
   half the elements would make reports readable. `scripts/metadata_feedback.py` detects the unit case offline.
3. **Beams, walls, slabs, foundations** use the generic bar-group comparison, tested on synthetic data only.
4. **Grid sort is lexical** (`K-10` sorts before `K-3`); cosmetic, in `run_comparison` ordering.
5. **Per-shop counts exclude plan-only self findings** (plausibility, peer outlier on plan elements). They appear in
   `findings.json`, the by-plan-sheet report and the XLSX.
6. **Accuracy is not measured** on real data: it needs the known-discrepancy list, which is not available here.
7. **ML tier (I9), 3D/IFC/UI extras** are not built.
8. `contract` and the guard scripts are stubs written from Plan 00; replace with Eric's versions on merge.
9. No end-to-end CI; `python scripts/check.py` is the gate.

## Quality gate

`python scripts/check.py`: ruff lint and format, 120+ tests, data guard. All pass.
