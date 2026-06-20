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
                        ├── 8. generate_rotation_matrix_tickets(): 22-red → 5 tickets 6+1
                        └── 9. archive → prediction_archive/YYYYXXX.txt

prediction_archive/ ──→ analyze_archive.py
                           ├── read archives + backfill actual results from lottery_data.json
                           └── export 3 patch types → config/*.latest.json (re-injected)
```

**Self-learning loop**: `predict → archive → analyze → patches → predict`

## Core Module Roles

| File | Role | Key Notes |
|------|------|-----------|
| `predict.py` | Main entry (~3500 lines) | team/single/team-cover modes; backtests; patch injection; anti-consensus debate |
| `project_config.py` | **Central config** | `ProjectConfig` dataclass → `to_runtime_config()` produces pool/fusion/matrix/blue/cover param groups |
| `agent_registry.py` | Expert registry | Fixed 8-expert set, excludes lstm |
| `blue_ball_engine.py` | Blue ball engine | 7-dim analysis (missing/parity/zone/amplitude/heat/moving-avg/Bayesian); params via config dict |
| `analyze_archive.py` | Offline analyzer | Reads archive KV format, backfills real results, exports 3 patch types + CSV/JSON reports |
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
  ├── generate_rotation_matrix_tickets()  # 22-red → 5 tickets 6+1
  │     └── _select_blue_ball_for_row()   # blue dedup selection
  └── _archive_prediction()        # write archive
```

Backtest entry points: `_run_team_backtest()` / `_run_team_cover_backtest()`

## Configuration System

`project_config.py::ProjectConfig` — single source of truth:

- **Pool**: `core_red_pool_size=22`, `core_blue_pool_size=10`, `rotation_matrix_type="22_red_cover_6_to_5"`
- **Ticketing**: `team_ticket_count=5`, `ticket_decay_step=0.06`, `min_ticket_decay=0.55`
- **Debate**: `debate_factor=0.6`, controls anti-consensus debate influence strength
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
- Current iteration plan: `docs/plans/2026-05-16-hit-rate-improvement-iteration-plan.md`
- Historical design docs: `docs/plans/`

## Current Behavior

- `team` mode always outputs `5` tickets of `6+1`
- Flow is expert proposals -> `build_core_pool_snapshot()` -> `generate_rotation_matrix_tickets()`
- `team-cover` mode also outputs `5` tickets, writes compact archive output, and marks `lead_summary.mode=team_cover`
- Position weights now affect core-pool scoring, not just row-local ordering
- `blue_params` flows into `BlueBallEngine` and can be overridden by `param patch`
- `row_weights` affects default matrix row order; current semantics are dynamic ordering, not dynamic elimination
- `--team-backtest` prints progress and reports final 5-ticket metrics
- `--team-cover-backtest` prints three-way comparison metrics for `team_cover`, `team`, and `conditional_random`, and does not write archives

## Hard Constraints

- Do not describe the project as an investment or guaranteed-winning tool
- Do not bypass stale-data protection unless the user explicitly wants offline experiments
- Do not overwrite an existing archive for the same period; re-predictions must use timestamped filenames (`YYYYXXX_timestamp.txt`)
- Do not change `team-cover` archive format silently; keep the existing compact archive format unless a separate experiment archive design is requested
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
- team-cover behavior changes: keep `README.md`, `SKILL.md`, `AGENTS.md`, and `test_predict.py` aligned
