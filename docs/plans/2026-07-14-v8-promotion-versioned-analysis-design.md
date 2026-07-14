# V8 Parameter Promotion, Versioned Analysis, and Backtest Cache Design

## Context and evidence

The V8 work starts from data through period `2026079` (draw date 2026-07-12). Before changing behavior, two clean offline reports were generated:

- Full stability: `prediction_archive/v8_stability_2026079.json`
  - 24 paired runs across windows 36/72/108/144 and seeds 7/42/101/202/777/2026.
  - Dynamic-vs-legacy objective delta mean `+0.009367`, bootstrap 95% CI `[+0.004390, +0.014148]`, positive in 19/24 runs.
  - The 36-cycle subgroup remains unstable: mean `+0.004537`, CI `[-0.010053, +0.019499]`, positive in only 3/6 runs.
  - Baseline runtime was about 63 minutes because dynamic and legacy independently rebuild the same expensive per-sample expert context.
- Rolling threshold calibration: `prediction_archive/v8_threshold_calibration_2026079.json`
  - Three expanding folds, 36-cycle training, immediately following 12-cycle validation blocks, seeds 7 and 42.
  - Selected one/two thresholds stayed at `0.42/0.58`; gap selected `0.06` in two folds and `0.02` in one.
  - Selected-vs-default validation delta was exactly `0.0` in all folds. There is no evidence to promote `min_score_gap=0.06` over the current `0.04`.
  - Baseline runtime was about 27 minutes. The existing report cache had only 6 hits against 60 misses because it caches complete evaluations only when all inputs are identical.

The evidence supports keeping the dynamic strategy, but it also demonstrates why parameter changes must not be promoted from training rank or concentration alone.

## Goals

1. Convert calibration evidence into a conservative, auditable promotion decision.
2. Never overwrite `config/param_patch.latest.json` from calibration automatically.
3. Group archive performance by reproducibility metadata while preserving legacy archives.
4. Reuse runtime-independent backtest preparation across strategy/threshold evaluations.
5. Split low-coupling reporting and provenance code out of `predict.py` only after behavior is protected by tests.

Non-goals: changing the five-ticket contract, changing the comparison objective, restoring LSTM, introducing external numeric dependencies, persistent cross-process cache files, or claiming predictive/financial guarantees.

## Alternatives considered

### A. Promote whenever mean validation uplift is positive

This is simple but unsafe. It ignores confidence intervals, fold disagreement, parameter concentration, minimum sample size, and the possibility that a tiny positive mean is noise. It would also encourage silently replacing the current patch. Rejected.

### B. Candidate-only multi-gate promotion review (chosen)

A pure review component consumes an exported calibration report and optionally the matching stability report. It returns `eligible` or `hold`, lists every gate and reason, and can write only a candidate artifact. Formal activation remains a separate human action. This is conservative, testable with synthetic reports, and fits the existing offline workflow.

### C. Bayesian optimizer or continuous hyperparameter search

This could model uncertainty more richly, but it adds complexity before the current discrete thresholds show measurable validation sensitivity. Deferred until the backtest engine is faster and more historical evidence exists.

## Parameter promotion guard

Create `parameter_promotion.py` with pure functions and a small CLI. The input contract is `threshold-calibration/v1`; an optional `stability-report/v2` adds a strategy-level safety gate. Default gates are deliberately conservative:

- at least 3 completed folds;
- at least 12 unseen validation samples per fold;
- a unique most-frequent threshold set with concentration ratio at least `2/3`;
- candidate thresholds must differ from the current/default threshold set;
- selected-vs-default mean must be strictly positive;
- selected-vs-default 95% CI lower bound must be at least zero;
- at least `2/3` of folds must have positive selected-vs-default delta;
- when stability is supplied: at least 12 paired runs, positive ratio at least `0.75`, and paired CI lower bound at least zero.

The decision payload records the source report fingerprints, selected candidate, default thresholds, observed metrics, gate results, and reasons. `eligible` writes `config/param_patch.candidate.json` (or an explicit path), never `.latest.json`. `hold` still writes an audit decision if requested but contains no activatable patch. With the current 2026079 evidence, the expected decision is `hold` because validation uplift is zero and the proposed gap does not outperform the default.

## Version-grouped archive analysis

`collect_explain_json_records()` will attach additive archive metadata to every parsed ticket row:

- `archive_schema_version`
- `runtime_config_hash`
- `patch_config_hash`
- `prediction_seed` (with legacy `seed` accepted as fallback)
- `git_commit`

Missing metadata is normalized to `legacy-unversioned`, so all 41 current legacy archive files remain analyzable. A new `build_version_group_report()` groups by the composite `(schema, commit, runtime hash, patch hash)` identity and reports ticket count, distinct period count, resolved-result count, average red hits, blue hit rate, average hit score, and >=2/>=3 red-hit rates. Seed is reported as a distribution rather than part of the version identity.

`render_report()` adds a compact version section. `export_reports()` adds `version_groups` to JSON and writes `<prefix>.versions.csv`. Existing ranking CSV and patch outputs remain unchanged. No existing compact archive lines are rewritten.

## Backtest cache optimization

The expensive invariant portion of `team_matrix_backtest_report()` is preparing each sample:

1. chronological history/target pair;
2. deterministic sample seed;
3. `train_lead_agent()` result;
4. eight-expert proposal teams.

These values do not depend on dynamic thresholds or the dynamic/legacy strategy. Introduce `backtest_cache.py` with a bounded in-memory LRU `BacktestContextCache`. Its key includes a canonical fingerprint of relevant record contents, cycle count, seed, initial weights, ticket count, and a cache schema version. It deliberately excludes runtime threshold/strategy fields. The value is the prepared sample sequence.

`team_matrix_backtest_report()` accepts an optional cache. Stability creates one shared cache so each dynamic/legacy pair prepares contexts once. Calibration keeps its existing exact-result memoizer and additionally shares a context cache among default evaluator calls; injected custom evaluators remain compatible and receive no new argument. The cache is request-scoped and bounded (default 8 entries) to avoid stale disk state and unbounded expert-proposal memory. Reports expose context-cache hits, misses, evictions, and prepared sample counts.

Correctness gates:

- cached and uncached reports must be deeply equal after removing cache telemetry;
- `train_lead_agent()` and `build_expert_teams()` call counts must drop for paired/candidate evaluations;
- changing records, cycles, seed, initial weights, or ticket count must miss the cache;
- no archive files are written by backtests.

## Final `predict.py` split

The split is intentionally last and behavior-preserving. Move only low-coupling code:

- `backtest_reporting.py`: objective/statistics, deterministic bootstrap, report export, threshold candidate construction, rolling fold construction, and runtime threshold patch construction;
- `archive_provenance.py`: canonical JSON hashing, patch hashing, Git commit lookup, and archive metadata construction;
- `backtest_cache.py`: prepared context cache types and keying;
- `parameter_promotion.py`: promotion review and CLI.

`predict.py` imports and re-exports public/private names currently used by tests and callers. Ticket generation, expert orchestration, and CLI mode routing remain in `predict.py` in this iteration to avoid circular dependencies and a risky giant rewrite.

## Error handling and compatibility

Malformed reports produce a clear `hold` decision or CLI validation error; they never produce a patch. Version grouping treats absent/malformed metadata as legacy rather than dropping records. Cache failures fall back to uncached preparation. All new JSON fields and archive analysis outputs are additive. The entertainment-only warning and fixed five-ticket behavior remain unchanged.

## Verification

Development follows red-green-refactor TDD. Focused tests cover promotion gate boundaries, legacy/mixed version groups, cache identity/equivalence/call reductions, module re-exports, and CLI help. Final verification runs `python -m unittest -v`, representative stability/calibration smoke runs, report JSON validation, and a clean Git diff review. No push occurs without explicit user instruction.
