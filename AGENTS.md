# AGENTS.md

This file gives non-Claude agents the minimum context needed to work in this repository. Use `README.md` as the full user-facing reference.

## Project Snapshot

- Repository purpose: entertainment-only Double Color Ball prediction and backtesting tool
- Main entry: `predict.py`
- Default flow: `team` mode
- Experimental flow: `team-cover` mode
- Config hub: `project_config.py` (`GLOBAL_CONFIG` singleton → `to_runtime_config()`)
- Expert registry: `agent_registry.py` (8 experts: hot/cold/missing/balanced/random/cycle/sum/zone)
- Analysis loop: `analyze_archive.py` + `prediction_archive/` + `config/*.latest.json`

## Architecture Overview

```
lottery_data.json ──→ predict.py (team mode pipeline)
                        │
                        ├── 1. _load_patches(): auto-load weight/matrix/param patches
                        ├── 2. differential_learning(): expert weight backtest learning
                        ├── 3. 8 expert proposals
                        ├── 4. build_core_pool_snapshot(): aggregate red pool (22) + blue pool (10)
                        │       └── position weights applied at scoring stage
                        ├── 5. _build_debate_pool(): anti-consensus debate (experts re-evaluate excluded 11 balls → re-rank)
                        ├── 6. BlueBallEngine.predict(): multi-dim blue scoring
                        ├── 7. _build_blue_debate(): blue anti-consensus debate (promote low-score blues with standout dimensions)
                        ├── 8. generate_team_matrix_tickets(): matrix + ticket-5 dynamic 0/1/2 offset
                        │       └── weakest row becomes ticket 5: preserve row or apply 1/2 evidence-backed offsets
                        └── 9. archive → prediction_archive/YYYYXXX.txt

prediction_archive/ ──→ analyze_archive.py
                           ├── read archives + backfill actual results from lottery_data.json
                           └── export 3 patch types → config/*.latest.json (re-injected)
```

**Self-learning loop**: `predict → archive → analyze → patches → predict`

## Core Module Roles

| File | Role | Key Notes |
|------|------|-----------|
| `predict.py` | Main entry / orchestration | team/single/team-cover modes; ticket generation; backtest workflows; patch injection; anti-consensus debate |
| `project_config.py` | **Central config** | `ProjectConfig` dataclass → `to_runtime_config()` produces pool/fusion/matrix/blue/cover param groups |
| `agent_registry.py` | Expert registry | Fixed 8-expert set, excludes lstm |
| `blue_ball_engine.py` | Blue ball engine | 7-dim analysis (missing/parity/zone/amplitude/heat/moving-avg/Bayesian); params via config dict |
| `analyze_archive.py` | Offline analyzer | Reads archive KV, backfills results, groups by reproducible version identity, exports 3 patch types + JSON/CSV/versions CSV |
| `archive_provenance.py` | Archive provenance | Canonical runtime/patch hashes plus schema/seed/commit metadata |
| `backtest_reporting.py` | Backtest reporting | Stability statistics, bootstrap CI, rolling-fold/candidate helpers, JSON/CSV export |
| `backtest_cache.py` | Backtest cache | Bounded LRU cache for invariant sample contexts, deterministic keys, telemetry |
| `parameter_promotion.py` | Promotion guard | Evidence gates; writes audit decision and candidate patch only; never activates latest patch |
| `enhanced_analysis.py` | Enhanced analysis | Pool influence, extended data fusion weights |
| `feature_importance.py` | Feature importance | Pearson/Spearman correlation, zero extra deps |
| `visual_analyzer.py` | Visualization | matplotlib charts (optional dep) |
| `update_data.py` | Data update | Playwright + BeautifulSoup scraping from 500.com |
| `manual_data_import.py` | Manual import | JSON/CSV/TXT external data import |

## Key Internal Functions (predict.py)

team mode call chain:

```
run_team_mode()
  ├── _load_patches()              # auto-discover weight/matrix/param patches
  ├── differential_learning()      # expert weight backtest learning
  ├── [8 × agent_*_propose()]      # per-expert proposals
  ├── build_core_pool_snapshot()   # weighted aggregation + position weight scoring
  ├── _build_debate_pool()         # anti-consensus debate: experts re-evaluate excluded 11 balls
  ├── BlueBallEngine(records, blue_params).predict()  # blue ball scoring
  ├── _build_blue_debate()         # blue debate: promote low-score blues with standout dimensions
  ├── generate_team_matrix_tickets()      # matrix + ticket-5 dynamic 0/1/2 offset
  │     ├── _build_offset_candidate_profiles() # independent counter-evidence over all 33 reds
  │     ├── _select_scientific_offset_reds()   # constrained 1/2-ball search for ticket 5
  │     ├── _choose_dynamic_offset_plan()      # threshold policy chooses 0/1/2
  │     └── _select_blue_ball_for_row()        # blue dedup selection
  └── _archive_prediction()        # write archive
```

Backtest entry points: `team_matrix_backtest_report()` / `team_cover_backtest_report()` / `team_stability_backtest_report()` / `team_threshold_calibration_report()`

## Configuration System

`project_config.py::ProjectConfig` — single source of truth:

- **Pool**: `core_red_pool_size=22`, `core_blue_pool_size=10`, `rotation_matrix_type="22_red_cover_6_to_5"`
- **Ticketing**: `team_ticket_count=5`, `ticket_decay_step=0.06`, `min_ticket_decay=0.55`, `anti_ticket_red_count=2`; ticket 5 defaults to `anti_ticket_strategy="dynamic"`; it preserves the original row or keeps 5/4 core plus 1/2 evidence-backed offsets
- **Debate**: `debate_factor=0.6`, controls anti-consensus debate influence strength
- **Dynamic offset**: `anti_ticket_dynamic_one_score_threshold=0.42`, `anti_ticket_dynamic_two_score_threshold=0.58`, `anti_ticket_dynamic_min_score_gap=0.04`, coverage gates `1/2`
- **Learning**: `learning_rate=0.25`, `decay_gamma=0.85`, `default_learn_cycles=30`
- **Blue ball**: all `blue_*` params flow via `to_runtime_config()["blue_params"]` → `BlueBallEngine`
- **Position weights**: `pos_weight_min=0.6`, `pos_weight_max=1.5` (applied at core pool scoring)

Patch coverage:
- `weight_patch`: expert base weight adjustments
- `matrix_patch`: `preferred_rows` / `row_weights`
- `param_patch`: any subset of pool/fusion/matrix/blue/cover params

## Patch Loading Priority

```
weight_patch:  --weight-patch explicit > config/weight_patch.latest.json > not loaded
matrix_patch:  config/matrix_patch.latest.json (auto) > built-in defaults
param_patch:   config/param_patch.latest.json (auto) > ProjectConfig defaults
```

Missing patch files do not block prediction — system falls back gracefully.

## Test Structure

| File | Coverage |
|------|----------|
| `test_predict.py` | predict.py core flow (PredictFlowTests) |
| `test_blue_engine.py` | BlueBallEngine scoring |
| `test_analyze_archive.py` | Archive analysis pipeline |
| `test_update_data.py` | Data update logic |

## Read First

- Full usage and CLI examples: `README.md`
- Repo maintainer notes: `AGENT.md`
- Claude Code entry: `CLAUDE.md`
- Skill trigger guide: `SKILL.md`
- Current iteration plan: `docs/plans/2026-07-14-v8-promotion-versioned-analysis-implementation-plan.md`
- Historical design docs: `docs/plans/`

## Current Behavior

- `team` mode always outputs `5` tickets of `6+1`; ticket 5 uses `dynamic_offset_0/1/2` by default
- Flow is expert proposals -> `build_core_pool_snapshot()` -> full-33 debate scores -> matrix tickets -> dynamic constrained offset decision
- `team-cover` mode also outputs `5` tickets, writes compact archive output, marks `lead_summary.mode=team_cover`, and appends schema/runtime/patch/seed/commit provenance keys
- Position weights now affect core-pool scoring, not just row-local ordering
- `blue_params` flows into `BlueBallEngine` and can be overridden by `param patch`
- `row_weights` affects default matrix row order; current semantics are dynamic ordering, not dynamic elimination
- `--team-backtest` prints progress and reports final 5-ticket metrics, counterfactual offset attribution, blue-rank calibration, and average ticket overlap
- `--team-cover-backtest` prints three-way comparison metrics for `team_cover`, `team`, and `conditional_random`, and does not write archives
- `--team-stability-backtest` pairs dynamic and legacy across windows/seeds, reports quantiles/bootstrap CI/grouped outcomes and robust score, can export JSON/CSV, and does not write archives
- `--team-threshold-calibration` uses expanding training prefixes and the immediately following unseen validation blocks; it can export JSON/CSV and never auto-writes a param patch
- Stability/calibration share bounded invariant-context caches and expose additive cache telemetry; cached and uncached reports must remain equivalent apart from telemetry
- `parameter_promotion.py` requires every configured evidence gate to pass, writes only `param_patch.candidate.json`-style output, refuses `param_patch.latest.json`, and requires human activation
- `analyze_archive.py` groups tickets by schema/commit/runtime/patch identity; missing provenance is `legacy-unversioned`; exports `<prefix>.versions.csv`
- Backtests default to clean runtime config and no archive-derived weight prior; `--backtest-use-current-patches` is an explicit offline sensitivity experiment

## Hard Constraints

- Do not describe the project as an investment or guaranteed-winning tool
- Do not bypass stale-data protection unless the user explicitly wants offline experiments
- Do not overwrite an existing archive for the same period; re-predictions must use timestamped filenames (`YYYYXXX_timestamp.txt`)
- Keep `team-cover` compact KV archive compatibility; V7 additive provenance keys are documented, but existing ticket/explain/lead-summary lines must not change silently
- Do not revert `team` mode to random ticket splitting or variable ticket counts without discussion
- Do not restore `LSTM/TensorFlow` or the `lstm` expert unless explicitly requested

## Commands

```bash
# Data & prediction
python update_data.py
python predict.py --mode team --num 5
python predict.py --mode team-cover --num 5 --seed 42

# Backtests
python predict.py --team-backtest --backtest-cycles 36 --seed 42
python predict.py --team-cover-backtest --backtest-cycles 36 --seed 42
python predict.py --team-stability-backtest --stability-windows 36,72,108,144 --stability-seeds 7,42,101,202,777,2026 --stability-export-prefix prediction_archive/stability_report
python predict.py --team-threshold-calibration --calibration-train-cycles 36 --calibration-validation-cycles 12 --calibration-folds 3 --calibration-seeds 42 --calibration-export-prefix prediction_archive/threshold_calibration
python parameter_promotion.py --calibration-report prediction_archive/threshold_calibration.json --stability-report prediction_archive/stability_report.json --output prediction_archive/promotion_decision.json --candidate-patch-output config/param_patch.candidate.json
# Offline sensitivity experiment only:
python predict.py --team-cover-backtest --backtest-use-current-patches --backtest-cycles 36 --seed 42

# Archive analysis
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report \
  --latest-patch-path config/weight_patch.latest.json \
  --latest-matrix-patch-path config/matrix_patch.latest.json \
  --latest-param-patch-path config/param_patch.latest.json

# Tests
python -m unittest -v
python -m unittest test_predict -v
python -m unittest test_predict.PredictFlowTests.test_agent_teams_excludes_lstm -v
```

## Keep In Sync

- Expert changes: `predict.py`, `analyze_archive.py`, `agent_registry.py`, docs
- CLI / output / patch behavior: `README.md`, `CLAUDE.md`, `SKILL.md`, `AGENTS.md`
- Config changes: `project_config.py` AND `blue_ball_engine.py` AND `to_runtime_config()` output AND `param_patch` injection
- `BlueBallEngine` param changes: `project_config.py` `blue_*` fields AND `to_runtime_config()["blue_params"]`
- Backtest metric changes: `README.md` command examples and wording
- Reporting/provenance helper changes: keep `predict.py` re-export compatibility plus `test_backtest_reporting.py` / `test_archive_provenance.py`
- Promotion-gate changes: keep audit schema, latest-patch refusal, README/SKILL/CLAUDE docs, and tests aligned
- Stability changes: keep dynamic/legacy paired runs, counterfactual fields, blue calibration, CLI docs, and tests aligned
- team-cover behavior changes: keep `README.md`, `SKILL.md`, `AGENTS.md`, and `test_predict.py` aligned
