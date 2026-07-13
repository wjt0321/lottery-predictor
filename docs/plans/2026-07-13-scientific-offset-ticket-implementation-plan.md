# Scientific Offset Ticket Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the fifth team ticket's inverse-score anti-consensus sampling with an evidence-backed, constrained combination selector while retaining a legacy fallback and fixed five-ticket output.

**Architecture:** Enrich the core/debate snapshot with full 33-ball scores, build explainable counter-evidence profiles for excluded balls, enumerate two-ball offset combinations around four retained core reds, and select the best valid combination using configurable evidence/coverage/structure/uncertainty weights. Integrate the result only at the existing weakest-ticket replacement point.

**Tech Stack:** Python standard library, `unittest`, existing `predict.py` pipeline, `ProjectConfig` runtime config, JSON-compatible explanation payloads.

---

### Task 1: Add runtime configuration contract

**Files:**
- Modify: `project_config.py`
- Test: `test_predict.py`

**Step 1: Write the failing test**

Add a test asserting `GLOBAL_CONFIG.to_runtime_config()["fusion_params"]` contains:

```python
{
    "anti_ticket_strategy": "scientific",
    "anti_ticket_candidate_limit": 6,
    "anti_ticket_standout_threshold": 0.65,
    "anti_ticket_min_standout_agents": 1,
    "anti_ticket_max_overlap": 4,
    "anti_ticket_sum_quantile_low": 0.10,
    "anti_ticket_sum_quantile_high": 0.90,
    "anti_ticket_score_weights": {
        "counter_evidence": 0.35,
        "coverage": 0.30,
        "structure": 0.20,
        "uncertainty": 0.15,
    },
}
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_project_config_exposes_scientific_offset_defaults -v`  
Expected: FAIL because keys are absent.

**Step 3: Implement minimal config fields**

Add matching `ProjectConfig` fields and emit them from `to_runtime_config()["fusion_params"]`. Keep `anti_ticket_red_count=2` for backward compatibility.

**Step 4: Run test to verify it passes**

Run the same unittest. Expected: PASS.

### Task 2: Preserve full red scoring evidence

**Files:**
- Modify: `predict.py` (`build_core_pool_snapshot`, `_build_debate_pool`)
- Test: `test_algorithm_correctness.py`

**Step 1: Write failing tests**

Assert that core snapshots expose `red_scores_full` for balls 1..33 and debate snapshots retain merged full scores for both promoted and excluded balls.

**Step 2: Verify RED**

Run the two new tests. Expected: FAIL because only pool scores are currently returned.

**Step 3: Implement minimal evidence storage**

Return all 33 fusion scores from `build_core_pool_snapshot`; after debate, replace `red_scores_full` with all merged scores while keeping `red_scores` pool-only for compatibility.

**Step 4: Verify GREEN**

Run new tests plus existing debate tests.

### Task 3: Build counter-evidence candidate profiles

**Files:**
- Modify: `predict.py`
- Test: `test_algorithm_correctness.py`

**Step 1: Write failing tests**

Create deterministic expert-score fixtures and assert:

- random/balanced do not count as independent standout support;
- candidates with multiple strong expert dimensions rank above unsupported absolute-bottom candidates;
- output includes JSON-safe score breakdown and reasons;
- candidate limit and minimum standout settings are honored.

**Step 2: Verify RED**

Run targeted tests. Expected: FAIL because `_build_offset_candidate_profiles` does not exist.

**Step 3: Implement minimal profile builder**

Add helpers for normalization and dispersion, then implement:

```python
def _build_offset_candidate_profiles(
    anti_candidates, records, lead_model, snapshot, runtime_config=None
) -> List[Dict[str, object]]:
    ...
```

Use `hot/cold/missing/cycle/sum/zone` as independent evidence views. Sort deterministically by counter-evidence then ball number.

**Step 4: Verify GREEN**

Run profile tests and all `test_algorithm_correctness` tests.

### Task 4: Implement constrained combination selector

**Files:**
- Modify: `predict.py`
- Test: `test_algorithm_correctness.py`

**Step 1: Write failing tests**

Assert the selector:

- keeps exactly the four highest-confidence base reds;
- selects two profiled anti candidates;
- prefers lower average overlap when evidence scores are close;
- rejects extreme parity/zone/sum combinations;
- is deterministic;
- falls back safely when no constrained combination exists.

**Step 2: Verify RED**

Expected: FAIL because `_select_scientific_offset_reds` does not exist.

**Step 3: Implement selector**

Add historical quantile and structure scoring helpers. Enumerate `itertools.combinations(profiles, 2)`, filter hard constraints, compute the configured weighted score, and return reds plus an explanation payload.

**Step 4: Verify GREEN**

Run targeted selector tests.

### Task 5: Integrate the fifth ticket and blue selection

**Files:**
- Modify: `predict.py` (`generate_team_matrix_tickets`)
- Test: `test_predict.py`

**Step 1: Write failing integration tests**

Assert that default team generation produces exactly one ticket with strategy `scientific_offset_2`, four model reds, two offset reds, a structured score breakdown, and an unused high-confidence blue. Assert `anti_ticket_strategy="legacy"` preserves the old path.

**Step 2: Verify RED**

Run targeted integration tests. Expected: FAIL due missing strategy.

**Step 3: Integrate minimal code**

Refactor the current nested anti-ticket builder into scientific and legacy paths. Replace only the weakest of five matrix tickets. Preserve fixed ticket count and archive shape.

**Step 4: Verify GREEN**

Run integration tests and existing matrix-ticket tests.

### Task 6: Documentation and regression verification

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `SKILL.md`

**Step 1: Update documentation**

Document the default one-ticket scientific offset strategy, config keys, legacy fallback, and entertainment-only limitation.

**Step 2: Run static and targeted checks**

Run:

```bash
python -m py_compile predict.py project_config.py test_algorithm_correctness.py test_predict.py
python -m unittest test_algorithm_correctness -v
python -m unittest test_predict -v
```

Expected: PASS.

**Step 3: Run full suite**

Run: `python -m unittest -v`  
Expected: all tests PASS.

### Task 7: Scientific vs legacy backtest

**Files:**
- No production file required unless diagnostics expose a defect.

**Step 1: Run 36-cycle scientific backtest**

Run `team_matrix_backtest_report` with default clean runtime and seed 42. Capture final metrics without writing archives.

**Step 2: Run 36-cycle legacy backtest**

Override `fusion_params.anti_ticket_strategy="legacy"` on the same samples and seed.

**Step 3: Compare acceptance metrics**

Report best-of-5 average score, red2+/red3+/red4+, same-ticket 4+1, at-least-4-plus-blue, final blue hit rate, and average overlap if available. Do not tune parameters after observing these 36 samples in this implementation pass.

**Step 4: Commit**

Stage source, tests, docs, and plan; commit with a focused feature message.

## Verification Result (2026-07-13)

Clean walk-forward comparison on the same 36 samples with `seed=42` (no archive patches):

| Metric | Scientific | Legacy | Delta |
|---|---:|---:|---:|
| Average ticket score | 1.2250 | 1.1917 | +0.0333 |
| Best-of-5 average score | 2.5417 | 2.5278 | +0.0139 |
| Red 2+ rate | 88.89% | 94.44% | -5.56 pp |
| Red 3+ rate | 38.89% | 36.11% | +2.78 pp |
| Red 4+ rate | 5.56% | 2.78% | +2.78 pp |
| Same-ticket 4 red + blue | 0/36 | 0/36 | 0 |
| At least 4 red + blue | 0/36 | 0/36 | 0 |
| Final blue hit rate | 30.56% | 30.56% | 0 |
| Average overlap | 0.800 | 0.800 | 0 |

The scientific path produced `scientific_offset_2` in all 36 samples. These results satisfy the implementation acceptance guardrails, but the sample is small and the rare joint-hit metrics remain zero; they do not establish a durable predictive advantage. No post-hoc parameter tuning was performed.
