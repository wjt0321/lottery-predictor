# AGENTS.md

This file gives non-Claude agents the minimum context needed to work in this repository. Use `README.md` as the full user-facing reference.

## Project Snapshot

- Repository purpose: entertainment-only Double Color Ball prediction and backtesting tool
- Main entry: `predict.py`
- Default flow: `team` mode
- Experimental flow: `team-cover` mode
- Analysis loop: `analyze_archive.py` + `prediction_archive/` + `config/*.latest.json`
- Expert registry: `agent_registry.py`

## Read First

- Full usage and CLI examples: `README.md`
- Repo maintainer notes: `AGENT.md`
- Skill trigger guide: `SKILL.md`
- Current iteration plan: `docs/plans/2026-05-16-hit-rate-improvement-iteration-plan.md`

## Current Behavior

- `team` mode always outputs `5` tickets of `6+1`
- Flow is expert proposals -> core pool -> rotation matrix -> archive
- `team-cover` mode also outputs `5` tickets, writes compact archive output, and marks `lead_summary.mode=team_cover`
- Position weights now affect core-pool scoring, not just row-local ordering
- `blue_params` flows into `BlueBallEngine` and can be overridden by `param patch`
- `row_weights` affects default matrix row order; current semantics are dynamic ordering, not dynamic elimination
- `--team-backtest` prints progress and reports final 5-ticket metrics
- `--team-cover-backtest` prints three-way comparison metrics for `team_cover`, `team`, and `conditional_random`, and does not write archives

## Hard Constraints

- Do not describe the project as an investment or guaranteed-winning tool
- Do not bypass stale-data protection unless the user explicitly wants offline experiments
- Do not overwrite an existing archive for the same period
- Do not change `team-cover` archive format silently; keep the existing compact archive format unless a separate experiment archive design is requested
- Do not revert `team` mode to random ticket splitting or variable ticket counts without discussion
- Do not restore `LSTM/TensorFlow` or the `lstm` expert unless explicitly requested

## Commands

```bash
python update_data.py
python predict.py --mode team --num 5
python predict.py --mode team-cover --num 5 --seed 42
python predict.py --team-backtest --backtest-cycles 36 --seed 42
python predict.py --team-cover-backtest --backtest-cycles 36 --seed 42
python analyze_archive.py --archive-dir prediction_archive --export-prefix prediction_archive/analysis_report
python -m unittest -v
```

## Keep In Sync

- Expert changes: `predict.py`, `analyze_archive.py`, `agent_registry.py`, docs
- CLI / output / patch behavior: `README.md`, `CLAUDE.md`, `SKILL.md`
- Config changes: `project_config.py` and `blue_ball_engine.py`
- Backtest metric changes: `README.md` command examples and wording
- team-cover behavior changes: keep `README.md`, `SKILL.md`, `AGENTS.md`, and `test_predict.py` aligned
