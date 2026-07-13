# V7 Stability Calibration and Reproducibility Design

## Goal

Extend the V6 dynamic-offset work with statistically richer stability reports, machine-readable exports, leakage-safe rolling threshold calibration, and additive archive provenance. The tool remains entertainment-only and all scores remain offline comparison objectives rather than probability estimates.

## Scope

1. Expand stability statistics with median, quartiles, deterministic bootstrap 95% confidence intervals, positive/negative/tie counts, and per-window/per-seed breakdowns.
2. Export stability and calibration results as JSON plus flat CSV files.
3. Add expanding-window threshold calibration. Each fold selects dynamic offset thresholds using only an older training prefix, then evaluates the selected thresholds on the immediately following unseen validation block.
4. Add archive metadata keys without changing existing ticket or explanation lines: schema version, runtime config hash, patch hash, prediction seed, and Git commit.
5. Add local memoization inside calibration so duplicate candidate/config evaluations are reused.

## Stability Report

`team_stability_backtest_report()` keeps the existing `runs` and `aggregate` keys, then adds a report schema identifier, generation metadata, quantiles and confidence intervals, and grouped summaries by window and seed. Bootstrap resampling uses a deterministic local RNG seed derived from the values, so identical input produces byte-stable statistics. Empty reports return zeros for all fields.

A new `export_backtest_report()` helper writes `<prefix>.json`, `<prefix>.runs.csv`, and `<prefix>.summary.csv`. JSON preserves the full nested report. Runs CSV contains one row per paired experiment. Summary CSV contains flattened aggregate statistics. Parent directories are created automatically and existing files are replaced only when the user explicitly supplies the same export prefix.

## Rolling Calibration

Calibration candidates are generated around the current dynamic thresholds. The default one-factor grid varies one threshold at a time, keeping runtime bounded; an optional Cartesian grid is available for deeper offline experiments. Invalid candidates, including a two-offset threshold lower than the one-offset threshold, are rejected.

Records are converted to oldest-first order. Each expanding fold consists of an older training prefix and the next unseen validation block. Candidate selection uses only training backtests. The chosen candidate, the unchanged default dynamic policy, and legacy policy are then evaluated on the validation prefix with `cycles=validation_block_size`; each target therefore sees only older history. Reports include fold cutoffs, selected thresholds, selection frequency, validation objectives, and paired deltas. No generated prediction archives are written.

## Archive Provenance

`save_compact_prediction()` accepts optional metadata. Existing calls and parsers remain valid. Prediction modes pass additive keys:

- `archive_schema_version=2`
- `runtime_config_hash=<sha256 prefix>`
- `patch_config_hash=<sha256 prefix or none>`
- `prediction_seed=<integer or none>`
- `git_commit=<short commit or unknown>`

Patch hashing uses file contents for the weight, parameter, and matrix patches that were actually discoverable. Runtime hashing uses canonical JSON. Team-cover retains the compact key-value format; only documented additive keys are introduced.

## Testing

Tests cover deterministic quantiles/CI, grouped stability summaries, export files, fold chronology, training-only candidate selection through an injected evaluator, cache reuse, CLI options, and archive metadata compatibility. Existing team, team-cover, stale-data, and archive overwrite protections remain unchanged. Full `unittest` is required before stopping.
