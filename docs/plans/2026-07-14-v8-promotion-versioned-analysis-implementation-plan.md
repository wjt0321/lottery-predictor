# V8 Parameter Promotion, Versioned Analysis, and Backtest Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add evidence-gated parameter promotion, version-grouped archive analysis, faster shared backtest preparation, and a final behavior-preserving split of low-coupling helpers out of `predict.py`.

**Architecture:** Keep ticket generation behavior unchanged. Add pure standalone modules for promotion review, cache infrastructure, reporting helpers, and provenance; inject or share caches through existing report workflows; preserve `predict.py` re-exports for compatibility.

**Tech Stack:** Python 3 standard library, `unittest`, JSON/CSV, `hashlib`, `OrderedDict`, Git CLI metadata.

---

### Task 1: Capture evidence and guardrail expectations

**Files:**
- Create: `docs/plans/2026-07-14-v8-promotion-versioned-analysis-design.md`
- Create: `docs/plans/2026-07-14-v8-promotion-versioned-analysis-implementation-plan.md`

**Steps:**
1. Record the 2026079 stability CI, subgroup weakness, calibration concentration, zero validation uplift, and baseline runtimes.
2. Document the chosen candidate-only promotion model and rejected alternatives.
3. Commit the design and plan before production code.

### Task 2: Parameter promotion review core

**Files:**
- Create: `parameter_promotion.py`
- Create: `test_parameter_promotion.py`

**Step 1: Write failing tests**

Cover:
- current 2026079-like report returns `hold` because selected-vs-default mean is zero;
- an eligible synthetic report passes every gate and emits the three fusion parameters;
- CI crossing zero, insufficient folds, insufficient validation samples, weak concentration, tied concentration, non-positive fold ratio, and unchanged candidate each produce explicit failed gates;
- optional stability evidence can hold an otherwise eligible candidate;
- malformed schema never produces a patch.

**Step 2: Run tests and verify RED**

Run: `python -m unittest test_parameter_promotion -v`

Expected: import/function failures.

**Step 3: Implement minimal pure review functions**

Implement canonical report hashing, threshold normalization, positive-fold counting, gate evaluation, decision payload construction, and candidate param-patch construction. Do not import `predict.py`.

**Step 4: Run tests and verify GREEN**

Run: `python -m unittest test_parameter_promotion -v`

Expected: all promotion tests pass.

**Step 5: Commit**

Commit message: `feat: add evidence-gated parameter promotion review`

### Task 3: Promotion CLI and candidate-only writes

**Files:**
- Modify: `parameter_promotion.py`
- Modify: `test_parameter_promotion.py`
- Modify: `README.md`

**Step 1: Write failing CLI tests**

Assert `--calibration-report`, optional `--stability-report`, gate override flags, `--output`, and `--candidate-patch-output`. Assert `hold` exits without writing a candidate patch and `eligible` writes only the requested candidate path.

**Step 2: Run and verify RED**

Run: `python -m unittest test_parameter_promotion -v`

**Step 3: Implement CLI**

Use atomic same-directory temporary writes followed by `os.replace`. Refuse a candidate output path whose basename is `param_patch.latest.json` unless a future explicit activation command is designed; this iteration has no activation command.

**Step 4: Run and verify GREEN**

Run: `python -m unittest test_parameter_promotion -v`

**Step 5: Smoke-test current reports**

Run:
`python parameter_promotion.py --calibration-report prediction_archive/v8_threshold_calibration_2026079.json --stability-report prediction_archive/v8_stability_2026079.json --output prediction_archive/v8_promotion_decision_2026079.json --candidate-patch-output config/param_patch.candidate.json`

Expected: decision `hold`; audit JSON written; candidate patch not written.

**Step 6: Commit**

Commit message: `feat: add candidate-only promotion CLI`

### Task 4: Version metadata collection and grouping

**Files:**
- Modify: `analyze_archive.py`
- Modify: `test_analyze_archive.py`

**Step 1: Write failing tests**

Create temporary archives containing:
- one legacy archive with no provenance;
- two archives sharing schema/commit/runtime/patch but different seeds;
- one archive with a different runtime hash.

Assert metadata is attached to ticket rows, legacy rows are retained, composite groups are correct, period counts are distinct, and resolved performance metrics are correct.

**Step 2: Run and verify RED**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests -v`

**Step 3: Implement grouping**

Add metadata normalization, composite version labels, seed distributions, and `build_version_group_report(records)`.

**Step 4: Run and verify GREEN**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests -v`

**Step 5: Commit**

Commit message: `feat: group archive analysis by reproducible version`

### Task 5: Version report rendering and export

**Files:**
- Modify: `analyze_archive.py`
- Modify: `test_analyze_archive.py`
- Modify: `README.md`

**Step 1: Write failing export tests**

Assert JSON contains `version_groups`, `<prefix>.versions.csv` is created, existing CSV/patch files remain, and rendered text includes `legacy-unversioned` plus version sample counts.

**Step 2: Run and verify RED**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests -v`

**Step 3: Implement additive output**

Pass version groups through `main()`, `render_report()`, and `export_reports()` without changing existing fields.

**Step 4: Run and verify GREEN**

Run: `python -m unittest test_analyze_archive.AnalyzeArchiveTests -v`

**Step 5: Commit**

Commit message: `feat: export version-grouped archive metrics`

### Task 6: Bounded backtest context cache

**Files:**
- Create: `backtest_cache.py`
- Create: `test_backtest_cache.py`

**Step 1: Write failing unit tests**

Cover deterministic record/weight fingerprints, hits, misses, LRU eviction, maximum-entry validation, and key changes for records/cycles/seed/weights/ticket count.

**Step 2: Run and verify RED**

Run: `python -m unittest test_backtest_cache -v`

**Step 3: Implement minimal cache**

Use `OrderedDict`; expose `get`, `put`, `get_or_prepare`, and telemetry. Keep the cache request-scoped and standard-library only.

**Step 4: Run and verify GREEN**

Run: `python -m unittest test_backtest_cache -v`

**Step 5: Commit**

Commit message: `feat: add bounded backtest context cache`

### Task 7: Integrate cache into matrix, stability, and calibration reports

**Files:**
- Modify: `predict.py` around `team_matrix_backtest_report()`, `team_stability_backtest_report()`, and `team_threshold_calibration_report()`
- Modify: `test_predict.py`

**Step 1: Write failing integration tests**

Assert:
- cached and uncached matrix reports are equal after removing cache telemetry;
- paired stability calls `train_lead_agent()`/`build_expert_teams()` once per sample rather than twice;
- calibration default evaluator shares preparation across threshold candidates and strategies;
- custom injected evaluators retain the old signature;
- cache telemetry is additive and deterministic.

**Step 2: Run and verify RED**

Run focused tests by full unittest names.

**Step 3: Extract sample preparation**

Add a helper that prepares `(history, target, sample_seed, lead_model, expert_teams)` and uses `BacktestContextCache`. Ensure cached values are not mutated; copy only if a test demonstrates mutation.

**Step 4: Share bounded caches**

- Stability: one cache with a small bound, reused by consecutive dynamic/legacy calls.
- Calibration: keep exact-result memoization and add one context cache for the default evaluator path.
- Matrix report: optional cache argument and additive telemetry.

**Step 5: Run focused tests and verify GREEN**

Run: `python -m unittest test_predict.PredictFlowTests -v`

**Step 6: Measure a small benchmark**

Run identical small stability/calibration smoke reports with cache disabled and enabled. Record wall time and verify report equality excluding telemetry.

**Step 7: Commit**

Commit message: `perf: reuse invariant backtest sample contexts`

### Task 8: Split pure backtest reporting helpers from `predict.py`

**Files:**
- Create: `backtest_reporting.py`
- Modify: `predict.py`
- Modify: `test_predict.py`
- Create or modify: `test_backtest_reporting.py`

**Step 1: Write characterization tests**

Cover objective calculation, deterministic stats/CI, grouped paired outcomes, threshold candidates, rolling folds, and JSON/CSV export through both `backtest_reporting` and `predict` re-exports.

**Step 2: Run characterization tests before movement**

Expected: existing `predict` assertions pass; new module imports fail.

**Step 3: Move pure helpers**

Move functions without importing `predict.py`. Parameterize runtime merge/default runtime where needed. Import/re-export names in `predict.py` to preserve callers and tests.

**Step 4: Run and verify GREEN**

Run: `python -m unittest test_backtest_reporting test_predict -v`

**Step 5: Commit**

Commit message: `refactor: extract backtest reporting helpers`

### Task 9: Split archive provenance helpers from `predict.py`

**Files:**
- Create: `archive_provenance.py`
- Modify: `predict.py`
- Modify: `test_predict.py`
- Create: `test_archive_provenance.py`

**Step 1: Write characterization tests**

Cover canonical runtime hashes, patch-content hashes, missing patches, Git commit injection, deterministic metadata, and `predict.build_archive_metadata` compatibility.

**Step 2: Verify RED for new module**

Run: `python -m unittest test_archive_provenance -v`

**Step 3: Move helpers and re-export**

Keep compact archive writing in `predict.py`; move only provenance construction and hashing.

**Step 4: Run and verify GREEN**

Run: `python -m unittest test_archive_provenance test_predict -v`

**Step 5: Commit**

Commit message: `refactor: extract archive provenance helpers`

### Task 10: Documentation and final verification

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `SKILL.md`
- Modify: `AGENTS.md`

**Steps:**
1. Document promotion gates, hold/eligible semantics, candidate-only paths, version grouping, cache telemetry, runtime guidance, and extracted modules.
2. Run syntax compilation: `python -m compileall -q .`.
3. Run focused suites: `python -m unittest test_parameter_promotion test_backtest_cache test_backtest_reporting test_archive_provenance test_analyze_archive test_predict -v`.
4. Run full suite: `python -m unittest -v`.
5. Run small stability and calibration CLI smoke exports and compare deterministic report fields.
6. Run current-report promotion CLI and verify `hold` plus no candidate patch.
7. Run `analyze_archive.py` export and inspect version JSON/CSV, including legacy group.
8. Review `git status`, `git diff --check`, and recent commits.
9. Stop locally without pushing unless the user explicitly requests a push.
