# §16 readiness audit (analytics)

Run on 2026-11-14 on a shared, loaded CPU (other sessions were training models and installing torch).
Status legend: met / not met / in progress / needs the team / not verified.

## Statistics

| Item | Status | Evidence | Remains |
|---|---|---|---|
| Public functions typed and documented (formula + source) | **in progress** | AST audit of 148 public functions outside `ml/ training/ ablation/`: 0 missing type hints; 114 flagged for docstrings (about half have none, the rest lack formula/source; the second check is a keyword heuristic, so expect some false flags). A separate "§16 docstrings" session owns the fix. | Re-run the audit after that session finishes. |
| Coverage ≥ 90% for `trend/`, `evidence/`, `spatial/` | **met in aggregate; 4 modules below 90% on the last run** | First run: TOTAL 95% (1565 stmts, 79 missed), every module ≥ 87%. Added `tests/analytics/unit/test_coverage_protocol_spatial.py` (11 tests, pass, ruff clean): `evidence/protocol.py` 87% → 98%, `spatial/product.py` 72% → 100%. | The last run (after the new file and concurrent edits by other sessions) showed `trend/ols.py` 79%, `trend/glsar.py` 78%, `trend/bootstrap.py` 69%, `trend/sen.py` 62%. They were ≥ 95% in the first run, so I suspect the other session's edits changed the statement count or the covered paths. Not investigated; re-run and confirm. Uncovered lines in other modules are listed in the run output (single lines, e.g. `evidence/alibi.py` 44, 53, 67, 120, 147, 187). |
| False alarms 3–7% for all corrected methods incl. real-series surrogates | not verified | `tests/analytics/statistical/` and `docs/validation/calibration_v1.md` exist. Slow tests were deselected in this run. | Run `-m slow` and read calibration_v1. |
| False `proven` < 1%, false `strong` < 5% on surrogates | not verified | See `calibration_v1.md`; `test_calibration_gate.py` is slow. | Same. |
| All reference cases pass; known artifacts never `proven` | not verified | Not run here. | Run the benchmark/reference suite. |
| Giovanni comparison for ≥ 5 series | **needs the team** | `test_giovanni_arctic.py` covers one series. | More Giovanni fixtures (human-supplied). |

## Own AI

Out of scope for this audit (ML sessions A6, A9, A10, A12 are active). Not assessed: gate files, model cards, reproducibility, "works without models". The advisory handling of the AI opinion is now tested: the `ai_expert` item is advisory, and the verdict is identical with or without it (`test_coverage_protocol_spatial.py`).

## General

| Item | Status | Evidence | Remains |
|---|---|---|---|
| Benchmarks within targets (§14) | **not met under load** (2 of 4 fail) | Medians, shared loaded CPU: full case 556 ms (target < 300 ms, FAIL); triangle 40 y 108 ms (< 100 ms, FAIL by 8%); bootstrap+BEAST 656 ms (< 3 s, ok); grid 1° OLS 2.05 s (< 5 s, ok). Also `test_radar_scan.py::test_stage1_speed_small` took 6.3–6.7 s vs a 5 s limit (it measured about 0.3 s earlier per its comment). Only 4 of the 9 §14 rows have benchmarks. | Re-run on an idle machine. Missing benchmarks: grid 0.25° MK+Sen, and the model rows (belong to the ML sessions). |
| `docs/methods/` covers every method, threshold, rule and model | in progress | Present: README, informant, new_dimensions, radar_story, varsearch. | No page yet for the core trend/evidence methods or the verdict rules; none for TrendNet. |

## Notes
- `tests/analytics/unit/test_ablation.py` (A11, mid-work) failed to collect and was ignored, as were the trendnet tests.
- Possible dead or buggy code: none identified.
- Nothing committed.
