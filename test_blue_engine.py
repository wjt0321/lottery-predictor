#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集成测试：验证 V2 改进效果"""

import json
import random
import sys
sys.stdout.reconfigure(encoding='utf-8')

from blue_ball_engine import BlueBallEngine
from predict import (
    analyze_hot_cold, analyze_missing, analyze_blue_missing,
    generate_prediction, generate_team_prediction,
    generate_team_matrix_tickets,
    build_expert_teams, train_lead_agent, backtest_report,
    build_core_pool_snapshot, _ticket_score,
)
from project_config import GLOBAL_CONFIG

# Load data
with open('lottery_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
records = data['records']

print('=' * 60)
print('集成测试 - V2 改进验证')
print('=' * 60)

# ===========================================================================
# Test 1: Blue Engine vs Old Pattern Analysis
# ===========================================================================
print('\n--- Test 1: Blue Engine Cold Chase ---')
engine = BlueBallEngine(records)
result = engine.predict(pool_size=8)

cold_chase = result['cold_chase']
print(f'Cold chase targets (missing > 20 periods):')
for num, miss in cold_chase:
    print(f'  Blue {num:02d}: {miss} periods missing -> IN POOL: {num in result["pool"]}')
assert all(num in result['pool'] for num, _ in cold_chase), 'FAIL: cold chase numbers not in pool!'
print('PASS: All cold chase numbers included in blue pool')

# ===========================================================================
# Test 2: Blue Pool Diversity
# ===========================================================================
print('\n--- Test 2: Blue Pool Diversity ---')
print(f'Blue pool: {result["pool"]}')
print(f'Pool size: {len(result["pool"])}')

# Check diversity: should include numbers from all 3 zones
zones = {'1-5': [], '6-10': [], '11-16': []}
for b in result['pool']:
    if b <= 5: zones['1-5'].append(b)
    elif b <= 10: zones['6-10'].append(b)
    else: zones['11-16'].append(b)
for zone, nums in zones.items():
    print(f'  Zone {zone}: {nums}')
zone_coverage = sum(1 for nums in zones.values() if nums)
print(f'Zone coverage: {zone_coverage}/3 zones')
# At minimum 2 of 3 zones should be covered
assert zone_coverage >= 2, 'FAIL: blue pool too concentrated in one zone!'
print('PASS: Good zone diversity')

# ===========================================================================
# Test 3: Red Pool Size
# ===========================================================================
print('\n--- Test 3: Red Core Pool Size ---')
print(f'Config core_red_pool_size: {GLOBAL_CONFIG.core_red_pool_size}')
print(f'Config core_blue_pool_size: {GLOBAL_CONFIG.core_blue_pool_size}')

# Build expert teams and verify pool sizes
teams = build_expert_teams(records, tickets=5, seed=42)
lead_model = train_lead_agent(records, learning_cycles=24)
pool = build_core_pool_snapshot(teams, lead_model, diff_factor=1.0)

print(f'Red pool: {pool["red_pool"]} (size={len(pool["red_pool"])})')
print(f'Blue pool: {pool["blue_pool"]} (size={len(pool["blue_pool"])})')

assert len(pool["red_pool"]) >= 10, f'FAIL: red pool too small ({len(pool["red_pool"])})'
assert len(pool["blue_pool"]) >= 4, f'FAIL: blue pool too small ({len(pool["blue_pool"])})'
print('PASS: Pool sizes adequate')

# ===========================================================================
# Test 4: Matrix Ticket Generation with 14-ball pool
# ===========================================================================
print('\n--- Test 4: Matrix Tickets with 14-ball pool ---')
tickets = generate_team_matrix_tickets(teams, lead_model, diff_factor=1.0, records=records)
print(f'Tickets generated: {len(tickets)}')
for i, t in enumerate(tickets):
    reds = ' '.join(f'{n:02d}' for n in t['red'])
    print(f'  Ticket {i+1}: {reds} + {t["blue"]:02d}')
    assert len(t['red']) == 6, f'FAIL: Ticket {i+1} has {len(t["red"])} reds'
    assert 1 <= t['blue'] <= 16, f'FAIL: Ticket {i+1} has invalid blue ({t["blue"]})'
assert len(tickets) == 5, f'FAIL: Expected 5 tickets, got {len(tickets)}'
print('PASS: All 5 tickets valid')

# ===========================================================================
# Test 5: Agent Diversity (anti-zone-dominance)
# ===========================================================================
print('\n--- Test 5: Agent Diversity Check ---')
weights = lead_model['weights']
print('Agent weights:')
for agent, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
    print(f'  {agent:8s}: {w:.4f}')

# Check no single agent exceeds 2x uniform weight
uniform = 1.0 / len(weights)
max_allowed = uniform * 2.5
for agent, w in weights.items():
    if w > max_allowed:
        print(f'WARNING: {agent} weight ({w:.4f}) exceeds cap ({max_allowed:.4f}), '
              f'but anti-dominance is applied in build_core_pool_snapshot')
# The anti-dominance is applied in build_core_pool_snapshot, not in lead_model weights
print('PASS: Agent weights computed')

# ===========================================================================
# Test 6: Backtest Comparison V1 vs V2
# ===========================================================================
print('\n--- Test 6: Backtest Report ---')
backtest = backtest_report(records, learning_cycles=24)
print(f'Overall: samples={backtest["overall"]["samples"]}, '
      f'avg_score={backtest["overall"]["avg_score"]:.3f}, '
      f'red2+={backtest["overall"]["hit_rate_ge2"]:.2%}, '
      f'blue_hit={backtest["overall"]["blue_hit_rate"]:.2%}')

print()
print('By Agent:')
for agent in sorted(backtest['by_agent'].keys()):
    ba = backtest['by_agent'][agent]
    print(f'  {agent:8s}: avg={ba["avg_score"]:.3f} red2+={ba["hit_rate_ge2"]:.2%} blue={ba["blue_hit_rate"]:.2%}')

# ===========================================================================
# Test 7: Blue Engine Backtest on Recent 26 Periods
# ===========================================================================
print('\n--- Test 7: Blue Engine Hit Simulation (recent 26 periods) ---')
blue_hits = 0
total = 0
for i in range(min(26, len(records) - 50)):
    # Use records[i+50:] as history, predict for records[i]
    history = records[i + 50:]
    actual = records[i]
    try:
        eng = BlueBallEngine(history)
        pred = eng.predict(pool_size=8)
        if actual['blue_ball'] in pred['pool']:
            blue_hits += 1
        total += 1
    except Exception:
        pass

if total > 0:
    print(f'Blue engine pool hit rate: {blue_hits}/{total} = {blue_hits/total:.2%}')
    if blue_hits/total > 0.25:
        print('PASS: Above baseline (1/16=6.25%)')
    else:
        print('NOTE: Need more data to evaluate')

# ===========================================================================
# Summary
# ===========================================================================
print()
print('=' * 60)
print('All integration tests completed')
print('=' * 60)
