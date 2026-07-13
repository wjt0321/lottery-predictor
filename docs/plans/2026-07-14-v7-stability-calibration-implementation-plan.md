# V7 Stability Calibration and Reproducibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add richer stability statistics and exports, leakage-safe rolling dynamic-threshold calibration, and reproducible archive metadata without changing five-ticket behavior.

**Architecture:** Extend the existing pure report helpers in `predict.py`, keep calibration orchestration separate from ticket generation, and inject the evaluator in tests. Preserve the compact archive as additive key-value fields and use only Python standard-library modules.

**Tech Stack:** Python 3, `unittest`, standard-library `csv`, `hashlib`, `statistics`-style calculations, JSON, Git CLI for optional commit metadata.

---

### Task 1: Rich deterministic stability statistics

**Files:**
- Modify: `predict.py:3802-3869`
- Test: `test_predict.py`

**Steps:**
1. Add failing tests for median, quartiles, bootstrap CI, empty input, and deterministic output.
2. Run the focused tests and confirm failure.
3. Implement percentile and deterministic bootstrap helpers; extend `_stability_stats()`.
4. Add grouped summaries by window and seed and paired positive/negative/tie counts.
5. Run focused tests and confirm pass.

### Task 2: JSON and CSV report export

**Files:**
- Modify: `predict.py`
- Test: `test_predict.py`

**Steps:**
1. Add a failing test that exports a synthetic stability report.
2. Verify JSON, runs CSV, and summary CSV expectations fail.
3. Implement `export_backtest_report()` and stable flattening helpers.
4. Add `--stability-export-prefix` and wire it to stability mode.
5. Run focused tests and confirm pass.

### Task 3: Leakage-safe rolling threshold calibration

**Files:**
- Modify: `predict.py`
- Test: `test_algorithm_correctness.py`
- Test: `test_predict.py`

**Steps:**
1. Add failing tests for candidate validation and chronological expanding folds.
2. Add a failing injected-evaluator test proving selection uses the training prefix and validation uses only the next block.
3. Implement candidate builders and fold construction.
4. Implement `team_threshold_calibration_report()` with per-run memoization.
5. Add validation comparisons against default dynamic and legacy.
6. Run focused tests and confirm pass.

### Task 4: Calibration CLI and exports

**Files:**
- Modify: `predict.py`
- Test: `test_predict.py`

**Steps:**
1. Add failing CLI help assertions.
2. Add `--team-threshold-calibration`, train/validation/fold/seed/grid options, and `--calibration-export-prefix`.
3. Add concise terminal reporting and reuse `export_backtest_report()` for JSON/CSV.
4. Run focused CLI tests and confirm pass.

### Task 5: Additive archive provenance

**Files:**
- Modify: `predict.py:1113-1150, 4621-4789`
- Test: `test_predict.py`

**Steps:**
1. Add a failing compatibility test for metadata lines and unchanged ticket parsing.
2. Implement canonical runtime hashing, patch-content hashing, and optional Git commit lookup.
3. Extend `save_compact_prediction()` with optional metadata.
4. Pass metadata from team and team-cover modes.
5. Run archive and mode tests and confirm pass.

### Task 6: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `SKILL.md`

**Steps:**
1. Document new commands, report files, leakage guardrails, metadata keys, and runtime cost guidance.
2. Run `python -m unittest test_algorithm_correctness -v`.
3. Run `python -m unittest test_predict -v`.
4. Run `python -m unittest -v`.
5. Run small CLI smoke tests for stability export and calibration export.
6. Review `git diff` and stop without pushing.
