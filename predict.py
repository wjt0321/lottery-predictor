#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预测脚本：支持单策略与多 Agent 团队协同预测。"""

import argparse
import csv
import hashlib
import json
import logging
import os
import random
import sys
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations, product
from typing import Dict, Iterable, List, Optional, Tuple, Set
import math

from agent_registry import AGENT_TEAMS
from project_config import GLOBAL_CONFIG
from blue_ball_engine import BlueBallEngine
from backtest_cache import BacktestContextCache, make_backtest_context_key

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from enhanced_analysis import calculate_enhanced_weights, apply_enhanced_weights
    ENHANCED_AVAILABLE = True
except ImportError:
    ENHANCED_AVAILABLE = False
    calculate_enhanced_weights = None
    apply_enhanced_weights = None


CONFIG = GLOBAL_CONFIG
DATA_FILE = CONFIG.data_file
ARCHIVE_DIR = CONFIG.archive_dir
DRAW_WEEKDAYS = set(CONFIG.draw_weekdays)
DRAW_CUTOFF_HOUR = CONFIG.draw_cutoff_hour
DRAW_CUTOFF_MINUTE = CONFIG.draw_cutoff_minute
TEAM_TICKET_COUNT = CONFIG.team_ticket_count
CORE_RED_POOL_SIZE = CONFIG.core_red_pool_size
CORE_BLUE_POOL_SIZE = CONFIG.core_blue_pool_size
ROTATION_MATRIX_TYPE = CONFIG.rotation_matrix_type
ROTATION_MATRIX_ROWS = CONFIG.rotation_matrix_rows
DEFAULT_RUNTIME_CONFIG = CONFIG.to_runtime_config()
CONDITIONAL_RANDOM_SOURCE = "conditional_random_baseline"
BACKTEST_UPLIFT_METRICS = (
    "avg_ticket_score",
    "best_of_5_avg_score",
    "best_of_5_hit_rate_ge2",
    "best_of_5_hit_rate_ge3",
    "best_of_5_hit_rate_4plus1",
    "best_of_5_hit_rate_ge4_plus_blue",
    "blue_pool_hit_rate",
    "final_blue_hit_rate",
    "avg_overlap",
)


def load_data():
    """加载数据"""
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze_hot_cold(records, recent_periods=None):
    """冷热号分析 - 优化：增加蓝球冷号分析；使用50期窗口捕捉中长趋势"""
    if recent_periods is None:
        recent_periods = CONFIG.hot_cold_window
    recent = records[:recent_periods]
    red_counts = Counter()
    blue_counts = Counter()
    
    for r in recent:
        red_counts.update(r['red_balls'])
        blue_counts.update([r['blue_ball']])
    
    for number in range(1, 34):
        red_counts.setdefault(number, 0)
    for number in range(1, 17):
        blue_counts.setdefault(number, 0)

    red_freq = sorted(red_counts.items(), key=lambda x: x[1], reverse=True)
    blue_freq = sorted(blue_counts.items(), key=lambda x: x[1], reverse=True)
    
    # 蓝球冷热分析
    hot_blue = [n for n, c in blue_freq[:5]]
    cold_blue = [n for n, c in blue_freq[-5:]]
    
    return {
        'hot_red': [n for n, c in red_freq[:10]],
        'cold_red': [n for n, _ in reversed(red_freq[-10:])],
        'hot_blue': hot_blue,
        'cold_blue': cold_blue,
        'red_freq': dict(red_freq),
        'blue_freq': dict(blue_freq)
    }


def analyze_blue_missing(records):
    """新增：蓝球遗漏分析"""
    last_seen = {i: -1 for i in range(1, 17)}
    
    for idx, r in enumerate(records):
        blue = r['blue_ball']
        if last_seen[blue] == -1:
            last_seen[blue] = idx
    
    blue_missing = {}
    for num in range(1, 17):
        if last_seen[num] == -1:
            blue_missing[num] = len(records)
        else:
            blue_missing[num] = last_seen[num]
    
    missing_sorted = sorted(blue_missing.items(), key=lambda x: x[1], reverse=True)
    
    return {
        'high_missing_blue': [num for num, count in missing_sorted[:5]],
        'blue_missing': blue_missing
    }


def analyze_missing(records):
    """遗漏值分析 - 优化：追踪连续遗漏期数"""
    last_seen = {i: -1 for i in range(1, 34)}
    
    for idx, r in enumerate(records):
        for ball in r['red_balls']:
            if last_seen[ball] == -1:
                last_seen[ball] = idx
    
    # 计算每个号码的遗漏期数（距离上次出现的期数）
    red_missing = {}
    for num in range(1, 34):
        if last_seen[num] == -1:
            red_missing[num] = len(records)  # 从未出现，遗漏期数=总记录数
        else:
            red_missing[num] = last_seen[num]  # 距离上次出现的期数
    
    # 按遗漏期数排序（遗漏越多越靠前）
    missing_sorted = sorted(red_missing.items(), key=lambda x: x[1], reverse=True)
    
    return {
        'high_missing_red': [num for num, count in missing_sorted[:10]],
        'red_missing': red_missing,
        'missing_sorted': missing_sorted
    }


def analyze_trend(records, periods=10):
    """新增：趋势分析 - 分析近期号码分布趋势"""
    if len(records) < periods:
        periods = len(records)
    
    recent = records[:periods]
    
    # 分析奇偶比
    odd_even_ratio = []
    for r in recent:
        odd_count = sum(1 for ball in r['red_balls'] if ball % 2 == 1)
        odd_even_ratio.append(odd_count)
    avg_odd = sum(odd_even_ratio) / len(odd_even_ratio)
    
    # 分析大小比（1-16小，17-33大）
    big_small_ratio = []
    for r in recent:
        big_count = sum(1 for ball in r['red_balls'] if ball >= 17)
        big_small_ratio.append(big_count)
    avg_big = sum(big_small_ratio) / len(big_small_ratio)
    
    # 分析区间分布（1-11, 12-22, 23-33）
    zone_distribution = {1: [], 2: [], 3: []}
    for r in recent:
        zone1 = sum(1 for ball in r['red_balls'] if 1 <= ball <= 11)
        zone2 = sum(1 for ball in r['red_balls'] if 12 <= ball <= 22)
        zone3 = sum(1 for ball in r['red_balls'] if 23 <= ball <= 33)
        zone_distribution[1].append(zone1)
        zone_distribution[2].append(zone2)
        zone_distribution[3].append(zone3)
    
    avg_zones = {
        1: sum(zone_distribution[1]) / len(zone_distribution[1]),
        2: sum(zone_distribution[2]) / len(zone_distribution[2]),
        3: sum(zone_distribution[3]) / len(zone_distribution[3])
    }
    
    return {
        'avg_odd': avg_odd,
        'avg_big': avg_big,
        'avg_zones': avg_zones
    }


def analyze_positions(records, recent_periods=60, min_weight=0.6, max_weight=1.5):
    """位置频率分析：红球按升序排列，6个位置各有统计规律。"""
    if len(records) < recent_periods:
        recent_periods = len(records)
    recent = records[:recent_periods]
    
    pos_freq = [Counter() for _ in range(6)]
    
    for r in recent:
        balls = sorted(r['red_balls'])
        for pos, ball in enumerate(balls):
            pos_freq[pos][ball] += 1
    
    min_weight = float(min_weight)
    max_weight = max(float(max_weight), min_weight)
    pos_weights = [{} for _ in range(6)]
    for pos in range(6):
        max_count = max(pos_freq[pos].values(), default=1) or 1
        for num in range(1, 34):
            freq = pos_freq[pos].get(num, 0)
            ratio = freq / max_count
            pos_weights[pos][num] = min_weight + ratio * (max_weight - min_weight)
    
    return {
        'pos_weights': pos_weights,
    }


# ============================================================================
# 新增：3个高级Agent分析函数
# ============================================================================

def analyze_cycle(records, max_period=50):
    """周期性分析（输入记录按从新到旧排序）。"""
    recent = records[:max_period]
    if len(recent) < 10:
        return {'cycle_scores': {}, 'top_cycle': []}

    cycle_scores = {}

    for number in range(1, 34):
        # 索引就是距离最近一期的期数（0 表示刚开出）。
        appearances = [i for i, r in enumerate(recent) if number in r['red_balls']]

        if len(appearances) < 3:
            cycle_scores[number] = 0
            continue

        # 相邻出现点的距离与时间方向无关，可直接用于估计历史周期。
        intervals = [appearances[i] - appearances[i - 1] for i in range(1, len(appearances))]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval <= 0:
            cycle_scores[number] = 0
            continue

        variance = (
            sum((gap - avg_interval) ** 2 for gap in intervals) / len(intervals)
            if len(intervals) > 1 else 0
        )
        stability = 1 / (1 + variance / (avg_interval ** 2))

        # 下一期开奖时，当前遗漏会从 appearances[0] 增加 1。
        next_gap = appearances[0] + 1
        distance = abs(next_gap - avg_interval)
        proximity_score = max(0.0, 1 - distance / avg_interval)
        cycle_scores[number] = stability * proximity_score
    
    # 按周期性得分排序
    sorted_cycles = sorted(cycle_scores.items(), key=lambda x: x[1], reverse=True)
    
    return {
        'cycle_scores': cycle_scores,
        'top_cycle': [num for num, score in sorted_cycles[:10] if score > 0],
        'cycle_strength': {num: score for num, score in sorted_cycles[:10]}
    }


def analyze_sum_trend(records, periods=30):
    """和值趋势分析：基于历史平均和值及标准差预测"""
    if len(records) < 5:
        return {'target_sum_range': (80, 130), 'sum_weights': {}}
    
    recent = records[:periods]
    sums = [sum(r['red_balls']) for r in recent]
    
    avg_sum = sum(sums) / len(sums)
    variance = sum((s - avg_sum) ** 2 for s in sums) / len(sums)
    std_sum = variance ** 0.5
    
    # 目标范围：平均和值 ± 1个标准差
    target_min = int(avg_sum - std_sum)
    target_max = int(avg_sum + std_sum)
    
    # 计算每个号码对和值的贡献权重
    sum_weights = {}
    for number in range(1, 34):
        # 该号码在历史开奖中的平均和值贡献
        appearances = [sum(r['red_balls']) for r in records if number in r['red_balls']]
        if appearances:
            avg_contribution = sum(appearances) / len(appearances)
            # 越接近目标平均和值，权重越高
            distance = abs(avg_contribution - avg_sum)
            sum_weights[number] = max(0, 1 - distance / (2 * std_sum)) if std_sum > 0 else 0.5
        else:
            sum_weights[number] = 0.3
    
    return {
        'target_sum_range': (target_min, target_max),
        'avg_sum': avg_sum,
        'std_sum': std_sum,
        'sum_weights': sum_weights,
        'sum_history': sums[:10]  # 最近10期和值
    }


def analyze_zone_balance(records, periods=20):
    """区间平衡分析：确保三区分布均衡"""
    if len(records) < 5:
        return {
            'target_zones': {1: 2, 2: 2, 3: 2},
            'zone_weights': {n: 1.0 for n in range(1, 34)}
        }
    
    recent = records[:periods]
    
    # 统计各区间的出现频率
    zone_counts = {1: Counter(), 2: Counter(), 3: Counter()}
    zone_distribution = {1: [], 2: [], 3: []}
    
    for r in recent:
        zone1_balls = [b for b in r['red_balls'] if 1 <= b <= 11]
        zone2_balls = [b for b in r['red_balls'] if 12 <= b <= 22]
        zone3_balls = [b for b in r['red_balls'] if 23 <= b <= 33]
        
        zone_distribution[1].append(len(zone1_balls))
        zone_distribution[2].append(len(zone2_balls))
        zone_distribution[3].append(len(zone3_balls))
        
        zone_counts[1].update(zone1_balls)
        zone_counts[2].update(zone2_balls)
        zone_counts[3].update(zone3_balls)
    
    # 计算平均分布
    avg_zone_dist = {
        1: sum(zone_distribution[1]) / len(zone_distribution[1]),
        2: sum(zone_distribution[2]) / len(zone_distribution[2]),
        3: sum(zone_distribution[3]) / len(zone_distribution[3])
    }
    
    # 目标分布：向均衡靠拢（理想是2-2-2）
    target_zones = {}
    for zone in [1, 2, 3]:
        # 如果某区偏少，下期应该多选
        if avg_zone_dist[zone] < 2:
            target_zones[zone] = min(3, int(2.5 - avg_zone_dist[zone] + 2))
        elif avg_zone_dist[zone] > 2:
            target_zones[zone] = max(1, int(2 - (avg_zone_dist[zone] - 2)))
        else:
            target_zones[zone] = 2
    
    # 为每个号码计算区间权重
    zone_weights = {}
    for number in range(1, 34):
        if number <= 11:
            zone = 1
        elif number <= 22:
            zone = 2
        else:
            zone = 3
        
        # 该区需要补充的号码数越多，权重越高
        zone_need = target_zones[zone]
        current_avg = avg_zone_dist[zone]
        
        if current_avg < zone_need:
            zone_weights[number] = 1.5  # 需要补充，权重提高
        elif current_avg > zone_need:
            zone_weights[number] = 0.7  # 过多，权重降低
        else:
            zone_weights[number] = 1.0  # 正常
    
    return {
        'target_zones': target_zones,
        'avg_zone_dist': avg_zone_dist,
        'zone_weights': zone_weights,
        'zone_hot': {
            1: [n for n, c in zone_counts[1].most_common(5)],
            2: [n for n, c in zone_counts[2].most_common(5)],
            3: [n for n, c in zone_counts[3].most_common(5)]
        }
    }


def _safe_red_sample(
    rng: random.Random, candidates: List[int], required: int = 6
) -> List[int]:
    """从候选集中加权不放回采样红球，不足时自动补齐。

    排名靠前的号码获得更高入选概率，避免候选池内部排名信息丢失。
    """
    unique_candidates = list(dict.fromkeys(candidates))
    if len(unique_candidates) < required:
        remaining = [i for i in range(1, 34) if i not in unique_candidates]
        unique_candidates.extend(rng.sample(remaining, required - len(unique_candidates)))

    if len(unique_candidates) <= required:
        return sorted(unique_candidates)

    # 加权不放回采样：排名越靠前权重越高
    # weight = exp(-rank * 0.3)，rank 从 0 开始
    selected = []
    pool = list(unique_candidates)
    while len(selected) < required and pool:
        weights = [math.exp(-idx * 0.3) for idx in range(len(pool))]
        total_w = sum(weights)
        r_val = rng.random() * total_w
        acc = 0.0
        for idx, w in enumerate(weights):
            acc += w
            if acc >= r_val:
                selected.append(pool.pop(idx))
                break
        else:
            selected.append(pool.pop(-1))
    return sorted(selected)


def _analyze_pairwise_cooccurrence(records, window=60):
    """分析红球两两共现频率。返回 {ball: [frequent_partners]}"""
    if len(records) < 20:
        return {}
    recent = records[:window]
    pair_count = defaultdict(Counter)
    single_count = Counter()
    for r in recent:
        reds = r['red_balls']
        single_count.update(reds)
        for i in range(len(reds)):
            for j in range(i+1, len(reds)):
                pair_count[reds[i]][reds[j]] += 1
                pair_count[reds[j]][reds[i]] += 1
    # Normalize: for each ball, rank partners by co-occurrence frequency
    result = {}
    for ball in range(1, 34):
        partners = pair_count.get(ball, Counter())
        total = single_count.get(ball, 1)
        scored = {p: c/total for p, c in partners.items()}
        top_partners = sorted(scored, key=scored.get, reverse=True)[:8]
        result[ball] = top_partners
    return result


def _simple_blue_score(records, window=60):
    """简化蓝球评分：频率+遗漏甜点区。避免极端冷热。"""
    if len(records) < 5:
        return {b: 0.5 for b in range(1, 17)}, list(range(1, 17))
    recent = records[:window]
    freq = Counter(r['blue_ball'] for r in recent)
    # 遗漏计算
    last_seen = {}
    for idx, r in enumerate(records):
        b = r['blue_ball']
        if b not in last_seen:
            last_seen[b] = idx
    scores = {}
    max_f = max(freq.values()) or 1
    for b in range(1, 17):
        f = freq.get(b, 0)
        miss = last_seen.get(b, len(records))
        # 甜点区：中等频率(25%-75%分位)+中等遗漏(5-15期)
        freq_score = 1.0 - abs(f/max_f - 0.5) * 2.0 if max_f > 0 else 0.5
        miss_score = 1.0 if 6 <= miss <= 22 else (0.65 if miss < 6 else 0.8)
        scores[b] = freq_score * 0.6 + miss_score * 0.4
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    pool = [b for b, _ in ranked[:8]]
    return scores, pool


def generate_prediction(records, strategy='balanced', rng: random.Random = None, use_enhanced=False):
    """按单策略生成预测号码 — 各专家用不同时间窗和方法去共识化。"""
    rng = rng or random.Random()
    if not records:
        return sorted(rng.sample(range(1, 34), 6)), rng.randint(1, 16)

    # 各专家用不同窗口分析 → 去共识化
    hc_short = analyze_hot_cold(records, recent_periods=30)
    hc_long = analyze_hot_cold(records, recent_periods=100)
    missing_data = analyze_missing(records)

    # 简化蓝球
    blue_scores, blue_candidates = _simple_blue_score(records)

    if strategy == 'hot':
        # 短期热度（30期窗口）
        candidates = hc_short['hot_red']
    elif strategy == 'cold':
        # 深度冷号（100期窗口）→ 捕捉长期冷门
        candidates = hc_long['cold_red']
    elif strategy == 'missing':
        candidates = missing_data['high_missing_red']
    elif strategy == 'balanced':
        # 多视角融合：短期热+长期冷+遗漏
        candidates = list(dict.fromkeys(hc_short['hot_red'][:5] + hc_long['cold_red'][:5] + missing_data['high_missing_red'][:5]))
    elif strategy == 'cycle':
        cycle_analysis = analyze_cycle(records, max_period=40)
        candidates = cycle_analysis['top_cycle'][:12]
        if not candidates:
            candidates = hc_short['hot_red'][:6] + missing_data['high_missing_red'][:6]
    elif strategy == 'sum':
        sum_analysis = analyze_sum_trend(records, periods=40)
        weighted_candidates = sorted(
            sum_analysis['sum_weights'].items(),
            key=lambda x: x[1], reverse=True
        )
        candidates = [n for n, w in weighted_candidates[:14]]
        if not candidates:
            candidates = hc_short['hot_red'][:7] + missing_data['high_missing_red'][:7]
    elif strategy == 'zone':
        zone_analysis = analyze_zone_balance(records, periods=30)
        candidates = []
        for zone in [1, 2, 3]:
            zone_hot = zone_analysis['zone_hot'][zone]
            need = zone_analysis['target_zones'][zone]
            candidates.extend(zone_hot[:need + 2])
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) < 10:
            candidates.extend(hc_short['hot_red'][:max(0, 10 - len(candidates))])
            candidates = list(dict.fromkeys(candidates))
    else:  # random
        return sorted(rng.sample(range(1, 34), 6)), rng.randint(1, 16)

    # 应用增强分析权重（如果启用且可用）
    if use_enhanced and ENHANCED_AVAILABLE and calculate_enhanced_weights:
        try:
            enhanced = calculate_enhanced_weights(records)
            red_weights = enhanced['red_weights']
            weighted_candidates = []
            for num in candidates:
                weight = red_weights.get(num, 1.0)
                weighted_candidates.append((num, weight))
            weighted_candidates.sort(key=lambda x: x[1], reverse=True)
            candidates = [num for num, _ in weighted_candidates[:14]]
        except Exception:
            pass

    red_balls = _safe_red_sample(rng, candidates, required=6)

    # 简化蓝球选择：甜点区加权采样
    if len(records) >= 5 and blue_candidates:
        bc_weights = [blue_scores.get(b, 0.5) for b in blue_candidates]
        total_w = sum(bc_weights)
        if total_w > 0:
            r_val = rng.random() * total_w
            acc = 0.0
            blue_ball = blue_candidates[-1]
            for b, w in zip(blue_candidates, bc_weights):
                acc += w
                if acc >= r_val:
                    blue_ball = b
                    break
        else:
            blue_ball = rng.choice(blue_candidates) if blue_candidates else rng.randint(1, 16)
    else:
        blue_ball = rng.randint(1, 16)

    return red_balls, blue_ball


def iterate_archived_cycles(
    records: List[Dict], min_history: int = 30, cycles: int = 24
) -> Iterable[Tuple[List[Dict], Dict]]:
    """按时间顺序滚动切片生成学习样本。"""
    if len(records) <= min_history:
        return []

    timeline = list(reversed(records))
    start_index = max(min_history, len(timeline) - cycles)

    samples = []
    for target_index in range(start_index, len(timeline)):
        samples.append((timeline[:target_index], timeline[target_index]))
    return samples


def _normalize_weights(values: List[float]) -> List[float]:
    total = sum(max(v, 0.0) for v in values)
    if total <= 0:
        return [1.0 / len(values)] * len(values) if values else []
    return [max(v, 0.0) / total for v in values]


def _normalize_agent_weights(raw_weights: Dict[str, float]) -> Dict[str, float]:
    cleaned = {agent: max(0.0, float(raw_weights.get(agent, 0.0))) for agent in AGENT_TEAMS}
    total = sum(cleaned.values())
    if total <= 0:
        return {agent: 1 / len(AGENT_TEAMS) for agent in AGENT_TEAMS}
    return {agent: cleaned[agent] / total for agent in AGENT_TEAMS}


def _stable_int_seed(*parts: object) -> int:
    """Build a repeatable seed from plain values without relying on hash()."""
    text = "|".join(str(part) for part in parts)
    acc = 0
    for char in text:
        acc = (acc * 131 + ord(char)) % (2**32)
    return acc


def load_weight_patch(patch_path: Optional[str]) -> Optional[Dict[str, float]]:
    if not patch_path:
        return None
    if not os.path.isfile(patch_path):
        return None
    try:
        with open(patch_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("recommended_base_weights"), dict):
        return _normalize_agent_weights(payload.get("recommended_base_weights", {}))
    deltas = payload.get("weight_deltas", {})
    if isinstance(deltas, dict):
        base = {agent: 1.0 / len(AGENT_TEAMS) for agent in AGENT_TEAMS}
        for agent in AGENT_TEAMS:
            base[agent] = max(0.0001, base[agent] + float(deltas.get(agent, 0.0)))
        return _normalize_agent_weights(base)
    return None


def find_default_weight_patch(project_root: Optional[str] = None) -> Optional[str]:
    root = project_root or os.getcwd()
    candidate = os.path.join(root, "config", "weight_patch.latest.json")
    return candidate if os.path.isfile(candidate) else None


def resolve_weight_patch_path(explicit_path: Optional[str], project_root: Optional[str] = None) -> Tuple[Optional[str], str]:
    if explicit_path:
        return explicit_path, "explicit"
    default_path = find_default_weight_patch(project_root=project_root)
    if default_path:
        return default_path, "default"
    return None, "none"


def _deep_merge_dict(base: Dict[str, object], override: Dict[str, object]) -> Dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_param_patch(patch_path: Optional[str]) -> Dict[str, object]:
    base_config = json.loads(json.dumps(DEFAULT_RUNTIME_CONFIG))
    if not patch_path or not os.path.isfile(patch_path):
        return base_config
    try:
        with open(patch_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return base_config
    if not isinstance(payload, dict):
        return base_config
    merged = _deep_merge_dict(base_config, payload)
    preferred_rows = merged.get("matrix_params", {}).get("preferred_rows", []) or []
    merged["matrix_params"]["preferred_rows"] = [int(row) for row in preferred_rows if str(row).isdigit()]
    return merged


def load_matrix_patch(patch_path: Optional[str]) -> Dict[str, object]:
    if not patch_path or not os.path.isfile(patch_path):
        return {}
    try:
        with open(patch_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    matrix_type = str(payload.get("matrix_type", "")).strip()
    row_weights = payload.get("row_weights", {}) or {}
    preferred_rows = payload.get("preferred_rows", []) or []
    cleaned_weights = {str(key): float(value) for key, value in row_weights.items() if str(key).isdigit()}
    cleaned_rows = [int(row) for row in preferred_rows if str(row).isdigit()]
    result = {"matrix_params": {}}
    if matrix_type:
        result["matrix_params"]["matrix_type"] = matrix_type
    if cleaned_weights:
        result["matrix_params"]["row_weights"] = cleaned_weights
    if cleaned_rows:
        result["matrix_params"]["preferred_rows"] = cleaned_rows
    return result


def find_default_param_patch(project_root: Optional[str] = None) -> Optional[str]:
    root = project_root or os.getcwd()
    candidate = os.path.join(root, "config", "param_patch.latest.json")
    return candidate if os.path.isfile(candidate) else None


def find_default_matrix_patch(project_root: Optional[str] = None) -> Optional[str]:
    root = project_root or os.getcwd()
    candidate = os.path.join(root, "config", "matrix_patch.latest.json")
    return candidate if os.path.isfile(candidate) else None


def resolve_runtime_config(project_root: Optional[str] = None) -> Dict[str, object]:
    runtime = load_param_patch(find_default_param_patch(project_root=project_root))
    matrix_overlay = load_matrix_patch(find_default_matrix_patch(project_root=project_root))
    return _deep_merge_dict(runtime, matrix_overlay)


def resolve_backtest_priors(
    use_current_patches: bool,
    explicit_weight_patch: Optional[str] = None,
    project_root: Optional[str] = None,
) -> Tuple[Dict[str, object], Optional[Dict[str, float]], str]:
    """Resolve fixed priors for an offline backtest.

    Backtests default to a clean configuration so patches learned from later
    archived draws cannot leak into earlier samples. Current patches are only
    loaded when the caller explicitly opts into that offline experiment.
    """
    if not use_current_patches:
        return json.loads(json.dumps(DEFAULT_RUNTIME_CONFIG)), None, "clean"

    patch_path, patch_source = resolve_weight_patch_path(
        explicit_weight_patch,
        project_root=project_root,
    )
    return (
        resolve_runtime_config(project_root=project_root),
        load_weight_patch(patch_path),
        patch_source,
    )


def _runtime_blue_params(runtime_config: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    blue_params = runtime.get("blue_params", {}) or {}
    return {str(key): value for key, value in blue_params.items()}


def _position_weight_factor(ball: int, pos_weights: Optional[List[Dict[int, float]]]) -> float:
    if not pos_weights:
        return 1.0
    factors = []
    for pos_map in pos_weights:
        if not isinstance(pos_map, dict):
            continue
        try:
            factors.append(float(pos_map.get(ball, 1.0)))
        except Exception:
            continue
    if not factors:
        return 1.0
    return sum(factors) / len(factors)


def build_archive_lead_summary(
    diff_factor: float,
    lead_report: Dict[str, object],
    patch_source: str,
    mode: str = "team",
) -> str:
    healthy_agents = lead_report.get("healthy_agents", []) or []
    archive_summary = lead_report.get("archive_summary", "")
    return (
        f"factor={diff_factor:.2f};mode={mode};patch_source={patch_source};"
        f"agents={','.join(healthy_agents)};report={archive_summary}"
    )


def _window_agent_performance(
    records: List[Dict],
    cycles: int,
    decay_gamma: float,
    num_trials: int = 10,
) -> Dict[str, object]:
    """评估 Agent 在滑动窗口上的表现，每个 Agent 每期运行多次取平均以降低随机噪声。"""
    samples = list(iterate_archived_cycles(records, cycles=cycles))
    if not samples:
        return {
            "cycles": cycles,
            "samples": 0,
            "avg_scores": {agent: 0.0 for agent in AGENT_TEAMS},
            "diff_scores": {agent: 0.0 for agent in AGENT_TEAMS},
        }

    avg_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    diff_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    weight_acc = 0.0

    for idx, (history_timeline, target) in enumerate(samples):
        history = list(reversed(history_timeline))
        round_weight = decay_gamma ** (len(samples) - idx - 1)
        # 每个 Agent 运行多次取平均，降低单次随机采样的噪声
        per_round_scores = {agent: 0.0 for agent in AGENT_TEAMS}
        for trial in range(num_trials):
            for agent in AGENT_TEAMS:
                rng = random.Random(_stable_int_seed("lead", cycles, target.get("period", idx), agent, trial))
                red, blue = generate_prediction(history, strategy=agent, rng=rng)
                per_round_scores[agent] += _ticket_score(red, blue, target)
        for agent in AGENT_TEAMS:
            per_round_scores[agent] /= num_trials

        team_avg = sum(per_round_scores.values()) / len(per_round_scores)
        for agent, score in per_round_scores.items():
            avg_scores[agent] += score * round_weight
            diff_scores[agent] += (score - team_avg) * round_weight
        weight_acc += round_weight

    if weight_acc <= 0:
        weight_acc = 1.0
    for agent in AGENT_TEAMS:
        avg_scores[agent] /= weight_acc
        diff_scores[agent] /= weight_acc

    # 趋势动量检测：后半段 vs 前半段
    mid = len(samples) // 2
    momentum = {agent: 0.0 for agent in AGENT_TEAMS}
    if mid >= 3:
        early_scores = {agent: 0.0 for agent in AGENT_TEAMS}
        late_scores = {agent: 0.0 for agent in AGENT_TEAMS}
        early_w = late_w = 0.0
        for idx, (history_timeline, target) in enumerate(samples):
            history = list(reversed(history_timeline))
            round_weight = decay_gamma ** (len(samples) - idx - 1)
            for agent in AGENT_TEAMS:
                trial_scores = []
                for trial in range(num_trials):
                    rng = random.Random(_stable_int_seed("trend", cycles, target.get("period", idx), agent, trial))
                    red, blue = generate_prediction(history, strategy=agent, rng=rng)
                    trial_scores.append(_ticket_score(red, blue, target))
                s = sum(trial_scores) / len(trial_scores)
                if idx < mid:
                    early_scores[agent] += s * round_weight
                    early_w += round_weight
                else:
                    late_scores[agent] += s * round_weight
                    late_w += round_weight
        if early_w > 0 and late_w > 0:
            for agent in AGENT_TEAMS:
                momentum[agent] = (late_scores[agent] / late_w) - (early_scores[agent] / early_w)

    return {
        "cycles": cycles,
        "samples": len(samples),
        "avg_scores": avg_scores,
        "diff_scores": diff_scores,
        "momentum": momentum,
    }


def _ticket_score(red: List[int], blue: int, actual: Dict) -> float:
    """统一评分：红球命中 + 蓝球加权命中。"""
    red_hits = len(set(red) & set(actual['red_balls']))
    blue_hit = 1 if blue == actual['blue_ball'] else 0
    return red_hits + blue_hit * 1.5


def train_lead_agent(
    records: List[Dict],
    learning_cycles: int = None,
    learning_rate: float = None,
    window_sizes: Optional[Tuple[int, ...]] = None,
    window_weights: Optional[Tuple[float, ...]] = None,
    decay_gamma: float = None,
    initial_weights: Optional[Dict[str, float]] = None,
    num_trials: int = 10,
) -> Dict[str, Dict[str, float]]:
    """主Agent差异学习：多窗口回测 + 时间衰减动态赋权。"""
    if learning_cycles is None:
        learning_cycles = CONFIG.default_learn_cycles
    if learning_rate is None:
        learning_rate = CONFIG.learning_rate
    if decay_gamma is None:
        decay_gamma = CONFIG.decay_gamma
    if window_sizes is None:
        window_sizes = (learning_cycles, learning_cycles * 2, learning_cycles * 4)
    valid_windows = tuple(sorted({max(8, int(w)) for w in window_sizes}))
    if window_weights is None:
        raw_weights = [1 / (idx + 1) for idx in range(len(valid_windows))]
    else:
        raw_weights = list(window_weights[:len(valid_windows)])
        if len(raw_weights) < len(valid_windows):
            raw_weights.extend([raw_weights[-1] if raw_weights else 1.0] * (len(valid_windows) - len(raw_weights)))
    normalized_window_weights = _normalize_weights(raw_weights)
    initial_normalized = _normalize_agent_weights(initial_weights or {})
    if initial_weights:
        prior_weights = {agent: max(CONFIG.min_ticket_weight, initial_normalized[agent] * len(AGENT_TEAMS)) for agent in AGENT_TEAMS}
    else:
        prior_weights = {agent: 1.0 for agent in AGENT_TEAMS}
    weights = dict(prior_weights)
    avg_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    diff_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    momentum_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    window_reports = []
    active_weight_total = 0.0

    for idx, cycles in enumerate(valid_windows):
        report = _window_agent_performance(records, cycles=cycles, decay_gamma=decay_gamma, num_trials=num_trials)
        report_weight = normalized_window_weights[idx]
        if report["samples"] <= 0:
            report_weight = 0.0
        window_reports.append(
            {
                "window": cycles,
                "weight": round(report_weight, 4),
                "samples": report["samples"],
            }
        )
        if report_weight <= 0:
            continue
        active_weight_total += report_weight
        for agent in AGENT_TEAMS:
            avg_scores[agent] += report["avg_scores"][agent] * report_weight
            diff_scores[agent] += report["diff_scores"][agent] * report_weight
            momentum_scores[agent] += report.get("momentum", {}).get(agent, 0.0) * report_weight

    if active_weight_total <= 0:
        normalized = {agent: 1 / len(AGENT_TEAMS) for agent in AGENT_TEAMS}
        return {
            "weights": normalized,
            "avg_scores": avg_scores,
            "diff_scores": diff_scores,
            "momentum": momentum_scores,
            "window_reports": window_reports,
            "meta": {
                "decay_gamma": decay_gamma,
                "learning_rate": learning_rate,
                "initial_weights_applied": bool(initial_weights),
            },
        }

    for agent in AGENT_TEAMS:
        avg_scores[agent] /= active_weight_total
        diff_scores[agent] /= active_weight_total
        momentum_scores[agent] /= active_weight_total
        performance_multiplier = max(0.05, 1.0 + learning_rate * diff_scores[agent])
        # 动量加成：上升期 +10% 权重，下降期 -10%
        momentum_bonus = 1.0 + max(-0.1, min(0.1, momentum_scores[agent] * 0.5))
        weights[agent] = max(0.03, prior_weights[agent] * performance_multiplier * momentum_bonus)

    total = sum(weights.values())
    normalized = {agent: weight / total for agent, weight in weights.items()}
    return {
        "weights": normalized,
        "avg_scores": avg_scores,
        "diff_scores": diff_scores,
        "momentum": momentum_scores,
        "window_reports": window_reports,
        "meta": {
            "decay_gamma": decay_gamma,
            "learning_rate": learning_rate,
            "initial_weights_applied": bool(initial_weights),
        },
    }


def backtest_report(
    records: List[Dict],
    learning_cycles: int = 24,
    windows: Optional[List[int]] = None,
    decay_gamma: float = 0.92,
) -> Dict[str, object]:
    if windows is None:
        windows = [learning_cycles, learning_cycles * 2, learning_cycles * 4]
    valid_windows = sorted({max(8, int(w)) for w in windows})

    overall = {
        "samples": 0,
        "avg_score": 0.0,
        "hit_rate_ge2": 0.0,
        "hit_rate_ge3": 0.0,
        "blue_hit_rate": 0.0,
    }
    by_agent = {
        agent: {"samples": 0, "avg_score": 0.0, "hit_rate_ge2": 0.0, "hit_rate_ge3": 0.0, "blue_hit_rate": 0.0}
        for agent in AGENT_TEAMS
    }
    window_reports = []

    for w in valid_windows:
        samples = list(iterate_archived_cycles(records, cycles=w))
        if not samples:
            window_reports.append({"window": w, "samples": 0, "avg_score": 0.0})
            continue
        window_scores = []
        window_weight_sum = 0.0
        for idx, (history_timeline, target) in enumerate(samples):
            history = list(reversed(history_timeline))
            round_weight = decay_gamma ** (len(samples) - idx - 1)
            team_round_scores = []
            for agent in AGENT_TEAMS:
                rng = random.Random(_stable_int_seed("backtest", w, target.get("period", idx), agent))
                red, blue = generate_prediction(history, strategy=agent, rng=rng)
                score = _ticket_score(red, blue, target)
                red_hits = len(set(red) & set(target["red_balls"]))
                blue_hit = 1 if blue == target["blue_ball"] else 0
                by_agent[agent]["samples"] += round_weight
                by_agent[agent]["avg_score"] += score * round_weight
                by_agent[agent]["hit_rate_ge2"] += (1.0 if red_hits >= 2 else 0.0) * round_weight
                by_agent[agent]["hit_rate_ge3"] += (1.0 if red_hits >= 3 else 0.0) * round_weight
                by_agent[agent]["blue_hit_rate"] += blue_hit * round_weight
                team_round_scores.append(score)
            team_avg = sum(team_round_scores) / len(team_round_scores)
            red_ge2 = sum(1 for s in team_round_scores if s >= 2.0) / len(team_round_scores)
            red_ge3 = sum(1 for s in team_round_scores if s >= 3.0) / len(team_round_scores)
            blue_rate = sum(1 for s in team_round_scores if s % 1.0 >= 0.5) / len(team_round_scores)
            overall["samples"] += round_weight
            overall["avg_score"] += team_avg * round_weight
            overall["hit_rate_ge2"] += red_ge2 * round_weight
            overall["hit_rate_ge3"] += red_ge3 * round_weight
            overall["blue_hit_rate"] += blue_rate * round_weight
            window_scores.append(team_avg)
            window_weight_sum += round_weight
        window_reports.append(
            {
                "window": w,
                "samples": len(samples),
                "avg_score": round(sum(window_scores) / len(window_scores), 4) if window_scores else 0.0,
            }
        )

    if overall["samples"] > 0:
        for key in ["avg_score", "hit_rate_ge2", "hit_rate_ge3", "blue_hit_rate"]:
            overall[key] = round(overall[key] / overall["samples"], 4)
        overall["samples"] = int(round(overall["samples"]))
    for agent in AGENT_TEAMS:
        denom = by_agent[agent]["samples"]
        if denom <= 0:
            continue
        for key in ["avg_score", "hit_rate_ge2", "hit_rate_ge3", "blue_hit_rate"]:
            by_agent[agent][key] = round(by_agent[agent][key] / denom, 4)
        by_agent[agent]["samples"] = int(round(denom))

    return {"overall": overall, "by_agent": by_agent, "window_reports": window_reports}


def _weighted_unique_sample(pool_scores: Dict[int, float], k: int, rng: random.Random) -> List[int]:
    """按权重无放回采样，兼顾稳定性与多样性。"""
    pool = dict(pool_scores)
    selected = []
    for _ in range(k):
        total = sum(max(score, 0.0001) for score in pool.values())
        cursor = rng.random() * total
        acc = 0.0
        pick = None
        for number, score in pool.items():
            acc += max(score, 0.0001)
            if acc >= cursor:
                pick = number
                break
        if pick is None:
            pick = next(iter(pool))
        selected.append(pick)
        pool.pop(pick, None)
    return sorted(selected)


def _weighted_choice(pool_scores: Dict[int, float], rng: random.Random) -> int:
    """按权重采样蓝球。"""
    total = sum(max(score, 0.0001) for score in pool_scores.values())
    cursor = rng.random() * total
    acc = 0.0
    for number, score in pool_scores.items():
        acc += max(score, 0.0001)
        if acc >= cursor:
            return number
    return 16


def generate_team_prediction(records: List[Dict], lead_model: Dict, rng: random.Random = None):
    """保留兼容的团队预测接口。"""
    rng = rng or random.Random()
    red_scores = {i: 0.0 for i in range(1, 34)}
    blue_scores = {i: 0.0 for i in range(1, 17)}

    for agent in AGENT_TEAMS:
        red, blue = generate_prediction(records, strategy=agent, rng=rng)
        base_weight = lead_model["weights"].get(agent, 0.0)
        diff_bonus = max(0.0, lead_model["diff_scores"].get(agent, 0.0)) * 0.2
        final_weight = base_weight * (1 + diff_bonus)

        for ball in red:
            red_scores[ball] += final_weight
        blue_scores[blue] += final_weight

    red_balls = _weighted_unique_sample(red_scores, k=6, rng=rng)
    blue_ball = _weighted_choice(blue_scores, rng=rng)
    return red_balls, blue_ball


def ensure_archive_dir() -> None:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)


def _archive_file_path(target_period: str) -> str:
    base_path = os.path.join(ARCHIVE_DIR, f"{target_period}.txt")
    if not os.path.exists(base_path):
        return base_path

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = os.path.join(ARCHIVE_DIR, f"{target_period}__{timestamp}.txt")
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(ARCHIVE_DIR, f"{target_period}__{timestamp}_{index}.txt")
        index += 1
    return candidate


def _canonical_json_hash(value: object, length: int = 16) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:max(8, int(length))]


def _patch_content_hash(patch_paths: Iterable[Optional[str]], length: int = 16) -> str:
    digest = hashlib.sha256()
    found = False
    normalized = sorted({os.path.abspath(path) for path in patch_paths if path and os.path.isfile(path)})
    for path in normalized:
        found = True
        digest.update(os.path.basename(path).encode("utf-8", errors="replace"))
        digest.update(b"\0")
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()[:max(8, int(length))] if found else "none"


def _current_git_commit(project_root: Optional[str] = None) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=project_root or os.getcwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else "unknown"


def build_archive_metadata(
    runtime_config: Dict[str, object],
    prediction_seed: Optional[int] = None,
    patch_paths: Iterable[Optional[str]] = (),
    git_commit: Optional[str] = None,
) -> Dict[str, str]:
    return {
        "archive_schema_version": "2",
        "runtime_config_hash": _canonical_json_hash(runtime_config),
        "patch_config_hash": _patch_content_hash(patch_paths),
        "prediction_seed": str(prediction_seed) if prediction_seed is not None else "none",
        "git_commit": str(git_commit or _current_git_commit()),
    }


def save_compact_prediction(
    target_period: str,
    tickets: List[Dict[str, object]],
    lead_summary: str,
    metadata: Optional[Dict[str, object]] = None,
) -> str:
    ensure_archive_dir()
    file_path = _archive_file_path(target_period)
    ticket_lines = []
    explain_lines = []
    explain_json_lines = []
    for index, ticket in enumerate(tickets, start=1):
        red_text = " ".join(f"{n:02d}" for n in ticket["red"])
        blue_text = f"{int(ticket['blue']):02d}"
        source_text = ",".join(ticket.get("sources", []))
        ticket_lines.append(f"ticket{index}={red_text}+{blue_text}|{source_text}")
        explain_text = str(ticket.get("explain", "")).replace("\n", " ").strip()
        if explain_text:
            explain_lines.append(f"ticket{index}_explain={explain_text}")
        explain_json = ticket.get("explain_json")
        if explain_json is not None:
            explain_json_lines.append(
                f"ticket{index}_explain_json={json.dumps(explain_json, ensure_ascii=False, separators=(',', ':'))}"
            )
    metadata = metadata or {}
    metadata_order = (
        "archive_schema_version",
        "runtime_config_hash",
        "patch_config_hash",
        "prediction_seed",
        "git_commit",
    )
    metadata_lines = [
        f"{key}={str(metadata[key]).replace(chr(10), ' ').replace(chr(13), ' ')}"
        for key in metadata_order
        if key in metadata
    ]
    lines = [
        f"period={target_period}",
        f"generated_at={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"ticket_count={len(tickets)}",
        f"lead_summary={lead_summary}",
        *metadata_lines,
        *ticket_lines,
        *explain_lines,
        *explain_json_lines,
    ]
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return file_path


def load_latest_archive() -> Optional[Dict[str, str]]:
    if not os.path.isdir(ARCHIVE_DIR):
        return None
    candidates = [name for name in os.listdir(ARCHIVE_DIR) if name.endswith(".txt")]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    file_name = candidates[0]
    file_path = os.path.join(ARCHIVE_DIR, file_name)
    values: Dict[str, str] = {}
    with open(file_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value
    values["file_path"] = file_path
    return values


def _parse_red_text(red_text: str) -> List[int]:
    numbers = []
    for token in red_text.split():
        if token.isdigit():
            numbers.append(int(token))
    return sorted(numbers[:6])


def evaluate_last_prediction_gap(
    latest_archive: Optional[Dict[str, str]], latest_record: Dict
) -> Dict[str, object]:
    if not latest_archive:
        return {
            "matched": False,
            "summary": "无历史精简预测，差异学习使用默认权重。",
            "factor": 1.0,
            "red_hits": 0,
            "blue_hit": 0,
        }
    archive_period = latest_archive.get("period", "")
    real_period = str(latest_record.get("period", ""))
    if archive_period != real_period:
        return {
            "matched": False,
            "summary": f"历史预测期号 {archive_period or '未知'} 与最新真实期号 {real_period} 不匹配，跳过差异评分。",
            "factor": 1.0,
            "red_hits": 0,
            "blue_hit": 0,
        }

    first_ticket = latest_archive.get("ticket1", "")
    ticket_part = first_ticket.split("|", 1)[0]
    red_part, blue_part = ("", "0")
    if "+" in ticket_part:
        red_part, blue_part = ticket_part.split("+", 1)
    predicted_red = _parse_red_text(red_part)
    predicted_blue = int(blue_part or "0")
    red_hits = len(set(predicted_red) & set(latest_record["red_balls"]))
    blue_hit = 1 if predicted_blue == latest_record["blue_ball"] else 0
    score = red_hits + blue_hit * 1.5
    if score >= 3:
        factor = 1.1
    elif score <= 1:
        factor = 0.9
    else:
        factor = 1.0
    summary = f"上期命中：红球 {red_hits} 个，蓝球 {'命中' if blue_hit else '未命中'}，差异调节系数 {factor:.2f}。"
    return {
        "matched": True,
        "summary": summary,
        "factor": factor,
        "red_hits": red_hits,
        "blue_hit": blue_hit,
    }


def build_expert_teams(records: List[Dict], tickets: int, seed: Optional[int]) -> Dict[str, Dict[str, object]]:
    teams: Dict[str, Dict[str, object]] = {}
    base_seed = seed if seed is not None else random.randint(1, 999999)
    for index, agent in enumerate(AGENT_TEAMS):
        proposals: List[Dict[str, object]] = []
        error_text = ""
        try:
            for ticket_index in range(tickets):
                team_rng = random.Random(base_seed + (index + 1) * 1000 + ticket_index)
                red, blue = generate_prediction(records, strategy=agent, rng=team_rng)
                proposals.append({"red": red, "blue": blue})
        except Exception as e:
            error_text = str(e)
        teams[agent] = {"proposals": proposals, "error": error_text}
    return teams


def _ball_sources(teams: Dict[str, Dict[str, object]], ticket_index: int) -> Tuple[Dict[int, List[str]], Dict[int, List[str]]]:
    red_sources: Dict[int, List[str]] = {}
    blue_sources: Dict[int, List[str]] = {}
    for agent, payload in teams.items():
        proposals = payload.get("proposals", [])
        if ticket_index >= len(proposals):
            continue
        proposal = proposals[ticket_index]
        for red in proposal["red"]:
            red_sources.setdefault(red, []).append(agent)
        blue = proposal["blue"]
        blue_sources.setdefault(blue, []).append(agent)
    return red_sources, blue_sources


def resolve_team_ticket_count(_requested: int) -> int:
    return TEAM_TICKET_COUNT


def _build_cover_blue_buckets(
    blue_ranked: List[int],
    blue_scores: Dict[int, float],
    records: Optional[List[Dict]] = None,
    runtime_config: Optional[Dict[str, object]] = None,
) -> Dict[str, List[int]]:
    """将蓝球候选按覆盖用途拆分成主攻/探索/回补三个桶。"""
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    bucket_size = int(runtime.get("cover_mode", {}).get("blue_bucket_size", CORE_BLUE_POOL_SIZE))
    ordered = list(blue_ranked[:max(0, bucket_size)])
    engine_pool: List[int] = []
    cold_chase: List[int] = []

    if records and len(records) >= 5:
        try:
            engine = BlueBallEngine(records, config=_runtime_blue_params(runtime))
            engine_result = engine.predict(pool_size=max(bucket_size, 6))
            engine_pool = [int(n) for n in engine_result.get("pool", []) if 1 <= int(n) <= 16]
            cold_chase = [
                int(num) for num, _miss in engine_result.get("cold_chase", [])
                if 1 <= int(num) <= 16
            ]
        except Exception:
            engine_pool = []
            cold_chase = []

    prioritized = engine_pool or ordered
    if not prioritized:
        return {"main": [], "explore": [], "reversion": []}

    main = prioritized[:2]
    explore = [n for n in cold_chase if n not in main][:2]

    remaining = [n for n in prioritized if n not in main and n not in explore]
    if len(remaining) < 2:
        fallback_order = ordered or sorted(blue_scores, key=lambda n: (-float(blue_scores.get(n, 0.0)), n))
        for number in fallback_order:
            if number not in main and number not in explore and number not in remaining:
                remaining.append(number)
            if len(remaining) >= 2:
                break
    reversion = remaining[:2]

    return {
        "main": main,
        "explore": explore,
        "reversion": reversion,
    }


def build_cover_candidate_snapshot(
    teams: Dict[str, Dict[str, object]],
    lead_model: Dict[str, Dict[str, float]],
    diff_factor: float,
    records: Optional[List[Dict]] = None,
    runtime_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """整理实验模式候选分布，弱化热点共识，保留结构标签。"""
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    pool_size = int(runtime.get("cover_mode", {}).get("candidate_pool_size", CORE_RED_POOL_SIZE))
    blue_pool_size = int(runtime.get("cover_mode", {}).get("blue_bucket_size", CORE_BLUE_POOL_SIZE))
    ticket_decay_step = float(runtime.get("fusion_params", {}).get("ticket_decay_step", 0.08))
    min_ticket_decay = float(runtime.get("fusion_params", {}).get("min_ticket_decay", 0.65))

    red_scores = {i: 0.0 for i in range(1, 34)}
    red_meta = {
        i: {
            "agents": set(),
            "zone": 1 if i <= 11 else 2 if i <= 22 else 3,
            "parity": i % 2,
        }
        for i in range(1, 34)
    }
    blue_scores = {i: 0.0 for i in range(1, 17)}
    valid_agents: List[str] = []

    for agent, payload in teams.items():
        proposals = payload.get("proposals", [])
        if not proposals:
            continue
        valid_agents.append(agent)
        base_weight = max(0.0, lead_model.get("weights", {}).get(agent, 0.0) * diff_factor)
        diff_bonus = max(0.0, lead_model.get("diff_scores", {}).get(agent, 0.0)) * 0.2
        final_weight = base_weight * (1 + diff_bonus)
        for proposal_index, proposal in enumerate(proposals):
            ticket_decay = max(min_ticket_decay, 1.0 - proposal_index * ticket_decay_step)
            weighted_score = final_weight * ticket_decay
            for red in proposal.get("red", []):
                if 1 <= int(red) <= 33:
                    red_scores[int(red)] += weighted_score
                    red_meta[int(red)]["agents"].add(agent)
            blue = int(proposal.get("blue", 0) or 0)
            if 1 <= blue <= 16:
                blue_scores[blue] += weighted_score

    for number in range(1, 34):
        meta = red_meta[number]
        agent_count = len(meta["agents"])
        if red_scores[number] <= 0:
            meta["agents"] = []
            continue
        if agent_count == 1:
            red_scores[number] *= 1.05
        elif agent_count >= 3:
            red_scores[number] *= 0.96
        meta["agents"] = sorted(meta["agents"])

    ranked_red = sorted(red_scores.items(), key=lambda item: (-item[1], item[0]))
    ranked_blue = sorted(blue_scores.items(), key=lambda item: (-item[1], item[0]))
    red_ranked = [n for n, score in ranked_red if score > 0][:pool_size]
    blue_ranked = [n for n, score in ranked_blue if score > 0][:blue_pool_size]

    return {
        "red_ranked": red_ranked,
        "red_scores": {n: round(float(red_scores[n]), 6) for n in red_ranked},
        "red_meta": {n: red_meta[n] for n in red_ranked},
        "blue_ranked": blue_ranked,
        "blue_scores": {n: round(float(blue_scores[n]), 6) for n in blue_ranked},
        "blue_buckets": _build_cover_blue_buckets(
            blue_ranked,
            blue_scores,
            records=records,
            runtime_config=runtime,
        ),
        "valid_agents": sorted(valid_agents),
    }


def _max_cover_overlap(candidate_red: List[int], tickets: List[Dict[str, object]]) -> int:
    if not tickets:
        return 0
    current = set(candidate_red)
    return max(len(current & set(ticket.get("red", []))) for ticket in tickets)


def _score_cover_red_combo(
    candidate_red: List[int],
    red_scores: Dict[int, float],
    red_meta: Dict[int, Dict[str, object]],
    tickets: List[Dict[str, object]],
    usage_counts: Counter,
) -> float:
    base_score = sum(float(red_scores.get(ball, 0.0)) for ball in candidate_red)
    overlap_penalty = 0.0
    for ticket in tickets:
        overlap = len(set(candidate_red) & set(ticket.get("red", [])))
        overlap_penalty += overlap * 1.25
        if overlap > 4:
            overlap_penalty += 50.0 + (overlap - 4) * 20.0

    # 分数仍是主导项；usage 只做弱惩罚，避免重新退化成“按使用次数优先排序”。
    reused_penalty = sum(usage_counts.get(ball, 0) * 0.10 for ball in candidate_red)
    fresh_bonus = sum(0.05 for ball in candidate_red if usage_counts.get(ball, 0) == 0)

    zones = {
        int(red_meta.get(ball, {}).get("zone", 1))
        for ball in candidate_red
    }
    odd_count = sum(1 for ball in candidate_red if int(red_meta.get(ball, {}).get("parity", ball % 2)) == 1)
    zone_bonus = len(zones) * 0.08 + (0.18 if len(zones) >= 3 else 0.0)
    parity_bonus = 0.08 if 2 <= odd_count <= 4 else 0.0

    return base_score + fresh_bonus + zone_bonus + parity_bonus - reused_penalty - overlap_penalty


def _assign_cover_blue(
    ticket_index: int,
    blue_buckets: Dict[str, List[int]],
    blue_ranked: List[int],
    blue_scores: Dict[int, float],
    used_blues: Set[int],
) -> Tuple[int, str]:
    bucket_order = ["main", "explore", "reversion", "main", "explore"]
    preferred_bucket = bucket_order[ticket_index % len(bucket_order)]

    def _ordered_bucket(numbers: List[int]) -> List[int]:
        if not numbers:
            return []
        order_index = {number: idx for idx, number in enumerate(numbers)}
        if all(number in blue_scores for number in numbers):
            return sorted(
                numbers,
                key=lambda n: (
                    -float(blue_scores.get(n, 0.0)),
                    order_index[n],
                ),
            )
        return list(numbers)

    def _pick_from(numbers: List[int], allow_reuse: bool = False) -> Optional[int]:
        ordered = _ordered_bucket(numbers)
        if not ordered:
            return None
        for candidate in ordered:
            if candidate not in used_blues:
                return candidate
        return ordered[0] if allow_reuse else None

    pick = _pick_from(list(blue_buckets.get(preferred_bucket, [])), allow_reuse=False)
    if pick is not None:
        return pick, preferred_bucket

    for fallback_bucket in ["main", "explore", "reversion"]:
        if fallback_bucket == preferred_bucket:
            continue
        pick = _pick_from(list(blue_buckets.get(fallback_bucket, [])), allow_reuse=False)
        if pick is not None:
            return pick, fallback_bucket

    if blue_ranked:
        ordered = _ordered_bucket(blue_ranked)
        for candidate in ordered:
            if candidate not in used_blues:
                return candidate, "fallback"
    pick = _pick_from(list(blue_buckets.get(preferred_bucket, [])), allow_reuse=True)
    if pick is not None:
        return pick, preferred_bucket
    for fallback_bucket in ["main", "explore", "reversion"]:
        if fallback_bucket == preferred_bucket:
            continue
        pick = _pick_from(list(blue_buckets.get(fallback_bucket, [])), allow_reuse=True)
        if pick is not None:
            return pick, fallback_bucket
    if blue_ranked:
        ordered = _ordered_bucket(blue_ranked)
        if ordered:
            return ordered[0], "fallback"
    return 1, "fallback"


def generate_team_cover_tickets(
    snapshot: Dict[str, object],
    runtime_config: Optional[Dict[str, object]] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, object]]:
    """基于候选分布逐注生成覆盖优先的 5 注实验票。"""
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    ticket_count = int(runtime.get("cover_mode", {}).get("ticket_count", TEAM_TICKET_COUNT))
    red_ranked = list(snapshot.get("red_ranked", []))
    red_scores = snapshot.get("red_scores", {}) or {}
    red_meta = snapshot.get("red_meta", {}) or {}
    blue_ranked = list(snapshot.get("blue_ranked", []))
    blue_scores = snapshot.get("blue_scores", {}) or {}
    blue_buckets = snapshot.get("blue_buckets", {}) or _build_cover_blue_buckets(
        blue_ranked,
        blue_scores,
        runtime_config=runtime,
    )
    valid_agents = list(snapshot.get("valid_agents", []))
    candidate_pool_size = int(runtime.get("cover_mode", {}).get("candidate_pool_size", len(red_ranked)))
    if len(red_ranked) < 6:
        return []

    rng = random.Random(seed if seed is not None else _stable_int_seed("team-cover", tuple(red_ranked)))
    _ = rng
    tickets: List[Dict[str, object]] = []
    usage_counts: Counter = Counter()
    used_blues: Set[int] = set()
    candidate_pool = list(red_ranked[:max(6, min(len(red_ranked), candidate_pool_size))])

    for ticket_index in range(ticket_count):
        best_red: Optional[List[int]] = None
        best_score: Optional[float] = None
        best_base_score: Optional[float] = None
        for combo in combinations(candidate_pool, 6):
            combo_red = sorted(combo)
            combo_score = _score_cover_red_combo(combo_red, red_scores, red_meta, tickets, usage_counts)
            combo_base = sum(float(red_scores.get(ball, 0.0)) for ball in combo_red)
            if (
                best_red is None
                or combo_score > (best_score or float("-inf"))
                or (
                    abs(combo_score - (best_score or float("-inf"))) < 1e-9
                    and combo_base > (best_base_score or float("-inf"))
                )
                or (
                    abs(combo_score - (best_score or float("-inf"))) < 1e-9
                    and abs(combo_base - (best_base_score or float("-inf"))) < 1e-9
                    and combo_red < best_red
                )
            ):
                best_red = combo_red
                best_score = combo_score
                best_base_score = combo_base
        final_red = best_red or sorted(candidate_pool[:6])

        blue_ball, blue_bucket = _assign_cover_blue(
            ticket_index,
            blue_buckets,
            blue_ranked,
            blue_scores,
            used_blues,
        )
        used_blues.add(blue_ball)
        for ball in final_red:
            usage_counts[ball] += 1

        source_agents = sorted(
            {
                agent
                for ball in final_red
                for agent in red_meta.get(ball, {}).get("agents", [])
            }
        ) or valid_agents
        focus = "score-anchor" if ticket_index == 0 else "coverage-balance"
        tickets.append(
            {
                "red": final_red,
                "blue": blue_ball,
                "sources": source_agents,
                "explain": (
                    f"cover_ticket={ticket_index + 1};focus={focus};"
                    f"blue_bucket={blue_bucket};blue={blue_ball:02d}"
                ),
                "explain_json": {
                    "cover_strategy": {
                        "mode": "team_cover",
                        "ticket_index": ticket_index + 1,
                        "focus": focus,
                        "blue_bucket": blue_bucket,
                        "candidate_blue_pool": [int(n) for n in blue_ranked],
                        "blue_bucket_candidates": [int(n) for n in blue_buckets.get(blue_bucket, [])],
                        "selected_blue": int(blue_ball),
                        "max_overlap_with_previous": _max_cover_overlap(final_red, tickets),
                    }
                },
            }
        )

    return tickets


def build_core_pool_snapshot(
    teams: Dict[str, Dict[str, object]],
    lead_model: Dict[str, Dict[str, float]],
    diff_factor: float,
    runtime_config: Optional[Dict[str, object]] = None,
    pos_weights: Optional[List[Dict[int, float]]] = None,
) -> Dict[str, object]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    core_red_pool_size = int(runtime.get("pool_params", {}).get("core_red_pool_size", CORE_RED_POOL_SIZE))
    core_blue_pool_size = int(runtime.get("pool_params", {}).get("core_blue_pool_size", CORE_BLUE_POOL_SIZE))
    ticket_decay_step = float(runtime.get("fusion_params", {}).get("ticket_decay_step", 0.08))
    min_ticket_decay = float(runtime.get("fusion_params", {}).get("min_ticket_decay", 0.65))
    red_scores = {i: 0.0 for i in range(1, 34)}
    blue_scores = {i: 0.0 for i in range(1, 17)}
    red_agent_contrib: Dict[int, Dict[str, float]] = {i: {} for i in range(1, 34)}
    blue_agent_contrib: Dict[int, Dict[str, float]] = {i: {} for i in range(1, 17)}
    pool_sources: Dict[int, Set[str]] = defaultdict(set)
    blue_sources: Dict[int, Set[str]] = defaultdict(set)
    valid_agents: List[str] = []

    # Anti-dominance: cap max agent weight to prevent single-agent takeover
    n_agents = len(AGENT_TEAMS)
    max_agent_weight = 2.0 / n_agents  # cap at 2x uniform weight

    for agent, payload in teams.items():
        proposals = payload.get("proposals", [])
        if not proposals:
            continue
        valid_agents.append(agent)
        base_weight = lead_model["weights"].get(agent, 0.0) * diff_factor
        # Apply anti-dominance cap
        base_weight = min(base_weight, max_agent_weight)
        diff_bonus = max(0.0, lead_model["diff_scores"].get(agent, 0.0)) * 0.2
        final_weight = base_weight * (1 + diff_bonus)
        for proposal_index, proposal in enumerate(proposals):
            ticket_decay = max(min_ticket_decay, 1.0 - proposal_index * ticket_decay_step)
            weighted_score = final_weight * ticket_decay
            for red in proposal["red"]:
                red_scores[red] += weighted_score
                pool_sources[red].add(agent)
                red_agent_contrib[red][agent] = red_agent_contrib[red].get(agent, 0.0) + weighted_score
            blue = proposal["blue"]
            blue_scores[blue] += weighted_score
            blue_sources[blue].add(agent)
            blue_agent_contrib[blue][agent] = blue_agent_contrib[blue].get(agent, 0.0) + weighted_score

    # Cross-agent diversity bonus: reward balls selected by multiple distinct agents
    for ball in range(1, 34):
        agent_count = len(pool_sources.get(ball, set()))
        if agent_count >= 3:
            red_scores[ball] *= 1.0 + min(0.3, (agent_count - 2) * 0.1)

    # Position weights are applied before matrix ticketing so they can affect
    # the core pool ordering instead of only shuffling numbers inside a row.
    if pos_weights:
        for ball in range(1, 34):
            if red_scores[ball] <= 0:
                continue
            red_scores[ball] *= _position_weight_factor(ball, pos_weights)

    ranked_red = sorted(red_scores.items(), key=lambda item: (-item[1], item[0]))
    ranked_blue = sorted(blue_scores.items(), key=lambda item: (-item[1], item[0]))
    red_pool = [ball for ball, score in ranked_red if score > 0][:core_red_pool_size]
    blue_pool = [ball for ball, score in ranked_blue if score > 0][:core_blue_pool_size]

    # Ensure pool reaches target size
    if len(red_pool) < core_red_pool_size:
        for ball, _ in ranked_red:
            if ball not in red_pool:
                red_pool.append(ball)
            if len(red_pool) >= core_red_pool_size:
                break
    if not blue_pool:
        blue_pool = [ball for ball, _ in ranked_blue[:1]] or [1]
    # Blue pool minimum diversity: ensure at least 4 blues if we have data
    if len(blue_pool) < max(4, core_blue_pool_size):
        for ball, _ in ranked_blue:
            if ball not in blue_pool:
                blue_pool.append(ball)
            if len(blue_pool) >= max(4, core_blue_pool_size):
                break

    return {
        "red_pool": red_pool,
        "blue_pool": blue_pool,
        "red_scores": {ball: round(float(red_scores[ball]), 6) for ball in red_pool},
        "red_scores_full": {ball: round(float(red_scores[ball]), 6) for ball in range(1, 34)},
        "blue_scores": {ball: round(float(blue_scores[ball]), 6) for ball in blue_pool},
        "pool_sources": {ball: sorted(pool_sources.get(ball, set())) for ball in red_pool},
        "blue_sources": {ball: sorted(blue_sources.get(ball, set())) for ball in blue_pool},
        "red_agent_contrib": red_agent_contrib,
        "blue_agent_contrib": blue_agent_contrib,
        "valid_agents": sorted(valid_agents),
        "agent_count_map": {ball: len(pool_sources.get(ball, set())) for ball in red_pool},
        "pos_weights": pos_weights,
    }


def _select_blue_ball_for_row(
    row_id: int,
    blue_pool: List[int],
    blue_scores: Dict[int, float],
    used_blues: Set[int],
    rng: random.Random,
    anti_engine: bool = True,
) -> int:
    """为特定行选择蓝球。

    anti_engine=True: 引擎反相关已证实，优先选引擎低分蓝球（反引擎策略）
    anti_engine=False: 传统方式，优先选引擎高分蓝球
    """
    if not blue_pool:
        return 1

    candidates = []
    for b in blue_pool:
        score = blue_scores.get(b, 0.5)
        candidates.append((b, score))

    # 反引擎：分数越低越优先；传统：分数越高越优先
    candidates.sort(key=lambda x: x[1], reverse=not anti_engine)

    unused_candidates = [(b, s) for b, s in candidates if b not in used_blues]

    if unused_candidates:
        if len(unused_candidates) >= 2:
            # 从未使用候选中取前2，随机选一个（保留一定随机性）
            pick_from = [b for b, _ in unused_candidates[:2]]
            return rng.choice(pick_from)
        return unused_candidates[0][0]

    return candidates[0][0]


def generate_rotation_matrix_tickets(
    snapshot: Dict[str, object],
    runtime_config: Optional[Dict[str, object]] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, object]]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    core_red_pool_size = int(runtime.get("pool_params", {}).get("core_red_pool_size", CORE_RED_POOL_SIZE))
    matrix_type = str(runtime.get("matrix_params", {}).get("matrix_type", ROTATION_MATRIX_TYPE))
    preferred_rows = runtime.get("matrix_params", {}).get("preferred_rows", []) or []
    raw_row_weights = runtime.get("matrix_params", {}).get("row_weights", {}) or {}
    row_weights = {int(k): float(v) for k, v in raw_row_weights.items() if str(k).isdigit()}

    # Select rotation matrix based on type
    MATRIX_REGISTRY = {
        "10_red_guard_6_to_5": (
            (0, 1, 2, 3, 4, 5),
            (0, 1, 2, 6, 7, 8),
            (0, 3, 4, 6, 7, 9),
            (1, 3, 5, 6, 8, 9),
            (2, 4, 5, 7, 8, 9),
        ),
        "14_red_guard_6_to_5": (
            (0, 1, 2, 3, 4, 5),
            (0, 1, 6, 7, 8, 9),
            (0, 2, 6, 10, 11, 12),
            (1, 3, 7, 10, 11, 13),
            (2, 4, 5, 8, 9, 12),
        ),
        "22_red_cover_6_to_5": GLOBAL_CONFIG.rotation_matrix_rows,
    }
    active_matrix = MATRIX_REGISTRY.get(matrix_type, GLOBAL_CONFIG.rotation_matrix_rows)
    matrix_row_count = len(active_matrix)

    if preferred_rows:
        row_order = [int(row_id) for row_id in preferred_rows if 1 <= int(row_id) <= matrix_row_count]
    else:
        weighted_rows = [(row_id, row_weights.get(row_id, 0.0)) for row_id in range(1, matrix_row_count + 1)]
        weighted_rows.sort(key=lambda item: (-item[1], item[0]))
        row_order = [row_id for row_id, _ in weighted_rows]

    red_pool = list(snapshot.get("red_pool", []))[:core_red_pool_size]
    blue_pool = list(snapshot.get("blue_pool", [])) or list(range(1, 17))
    blue_scores = snapshot.get("blue_scores", {}) or {b: 1.0 for b in blue_pool}
    pool_sources = snapshot.get("pool_sources", {}) or {}
    blue_sources = snapshot.get("blue_sources", {}) or {}
    red_agent_contrib = snapshot.get("red_agent_contrib", {}) or {}
    blue_agent_contrib = snapshot.get("blue_agent_contrib", {}) or {}
    valid_agents = list(snapshot.get("valid_agents", []))
    pos_weights = snapshot.get("pos_weights", None)
    if len(red_pool) < core_red_pool_size:
        return []

    tickets: List[Dict[str, object]] = []
    used_blues: Set[int] = set()
    rng_seed = seed
    if rng_seed is None:
        rng_seed = _stable_int_seed(
            "rotation-matrix",
            matrix_type,
            tuple(red_pool),
            tuple(blue_pool),
            tuple(row_order),
        )
    rng = random.Random(rng_seed)

    def _count_overlap(red_a: List[int], red_b: List[int]) -> int:
        return len(set(red_a) & set(red_b))

    def _find_best_swap(row_red: List[int], pool: List[int], row_indices: Tuple[int, ...],
                        pool_sources: Dict[int, Set[str]], red_agent_contrib: Dict[int, Dict[str, float]],
                        existing_tickets: List[Dict]) -> Optional[Tuple[int, int]]:
        """找到最优交换：换出后能使与所有已生成票的最大重叠度降低最多的号码。"""
        # 计算每个号码的可替换优先级（分数越低、共识越少越优先）
        scored = []
        for idx in row_indices:
            ball = pool[idx]
            agent_count = len(pool_sources.get(ball, set()))
            contrib = red_agent_contrib.get(ball, {})
            max_contrib = max(contrib.values()) if contrib else 0.0
            scored.append((idx, ball, max_contrib, agent_count))
        # 按可替换优先级排序：agent_count 少的优先，分数低的优先
        scored.sort(key=lambda x: (x[3], x[2]))

        # 当前与所有已生成票的最大重叠
        current_max_overlap = max(
            (_count_overlap(row_red, t["red"]) for t in existing_tickets),
            default=0
        )

        best_swap = None
        best_improvement = 0

        for replace_idx, replace_ball, _, _ in scored:
            # 尝试每个不在当前 row 的替代号码
            for alt_idx, alt_ball in enumerate(pool):
                if alt_idx in row_indices:
                    continue
                # 模拟替换后的新 row
                new_red = sorted([alt_ball if b == replace_ball else b for b in row_red])
                # 计算替换后与所有已生成票的最大重叠
                new_max_overlap = max(
                    (_count_overlap(new_red, t["red"]) for t in existing_tickets),
                    default=0
                )
                improvement = current_max_overlap - new_max_overlap
                # 优先选择改进最大的；如果改进相同，优先替换优先级高的（排前面的）
                if improvement > best_improvement or (improvement == best_improvement and best_swap is None):
                    best_improvement = improvement
                    best_swap = (replace_idx, alt_idx)

        return best_swap

    for row_id in row_order:
        row = active_matrix[row_id - 1]
        # Validate row indices against pool
        if max(row) >= len(red_pool):
            continue
        final_red = sorted(red_pool[index] for index in row)

        # 多样性约束：迭代检查并修复与已生成注的红球重叠度
        diversity_replacements = []
        max_attempts = 3  # 每行最多尝试 3 次替换
        for _attempt in range(max_attempts):
            if not tickets:
                break
            # 找出与当前行重叠最大的已生成票
            worst_overlap = 0
            worst_ticket = None
            for existing in tickets:
                overlap = _count_overlap(final_red, existing["red"])
                if overlap > worst_overlap:
                    worst_overlap = overlap
                    worst_ticket = existing
            # 如果最大重叠 < 4，满足多样性约束
            if worst_overlap < 4:
                break
            # 尝试找到最优替换
            swap = _find_best_swap(final_red, red_pool, row, pool_sources, red_agent_contrib, tickets)
            if swap:
                old_idx, new_idx = swap
                old_ball = red_pool[old_idx]
                new_ball = red_pool[new_idx]
                final_red = sorted([new_ball if b == old_ball else b for b in final_red])
                diversity_replacements.append({
                    "replaced": int(old_ball),
                    "replacement": int(new_ball),
                    "reason": f"overlap_{worst_overlap}_with_row_{worst_ticket['matrix_row_id']}"
                })
            else:
                break  # 找不到可替换的号码

        # 蓝球混合策略：RM票用引擎高分，反共识票用引擎低分
        final_blue = _select_blue_ball_for_row(
            row_id, blue_pool, blue_scores, used_blues, rng, anti_engine=False
        )
        used_blues.add(final_blue)
        source_agents = set()
        red_contrib_json = []
        red_contrib_parts = []
        for ball in final_red:
            source_agents.update(pool_sources.get(ball, []))
            contribs = red_agent_contrib.get(ball, {}) or {}
            top_agent, top_score = ("na", 0.0)
            if contribs:
                top_agent, top_score = max(contribs.items(), key=lambda x: x[1])
            red_contrib_parts.append(f"{ball:02d}:{top_agent}({top_score:.3f})")
            red_contrib_json.append(
                {
                    "ball": int(ball),
                    "top_agent": top_agent,
                    "top_contribution": round(float(top_score), 6),
                    "agent_contributions": {
                        a: round(float(s), 6) for a, s in sorted(contribs.items(), key=lambda x: x[1], reverse=True)
                    },
                }
            )
        source_agents.update(blue_sources.get(final_blue, []))
        blue_contribs = blue_agent_contrib.get(final_blue, {}) or {}
        blue_agent, blue_score = ("na", 0.0)
        if blue_contribs:
            blue_agent, blue_score = max(blue_contribs.items(), key=lambda x: x[1])
        explain = (
            f"来源Agent={','.join(sorted(source_agents) or valid_agents)};"
            f"红球贡献={','.join(red_contrib_parts)};"
            f"蓝球贡献={final_blue:02d}:{blue_agent}({blue_score:.3f});"
            f"矩阵类型={matrix_type};"
            f"矩阵行={row_id};"
            f"覆盖池位={','.join(str(index + 1) for index in row)}"
        )
        explain_json = {
            "sources": sorted(source_agents) or valid_agents,
            "red": red_contrib_json,
            "blue": {
                "ball": int(final_blue),
                "top_agent": blue_agent,
                "top_contribution": round(float(blue_score), 6),
                "agent_contributions": {
                    a: round(float(s), 6) for a, s in sorted(blue_contribs.items(), key=lambda x: x[1], reverse=True)
                },
            },
            "diversity_replacements": diversity_replacements,
            "matrix": {
                "type": matrix_type,
                "row_id": row_id,
                "row_weight": round(float(row_weights.get(row_id, 0.0)), 6),
                "covered_pool_positions": [index + 1 for index in row],
            },
            "core_pool": {
                "red_pool": [int(ball) for ball in red_pool],
                "blue_pool": [int(ball) for ball in blue_pool],
            },
        }
        tickets.append(
            {
                "red": final_red,
                "blue": final_blue,
                "sources": sorted(source_agents) or valid_agents,
                "valid_agents": valid_agents,
                "explain": explain,
                "explain_json": explain_json,
                "diversity_replacements": diversity_replacements,
                "matrix_row_id": row_id,
            }
        )
    return tickets


# ══════════════════════════════════════════════════════════════════════════════
# 反共识辩论机制 (Anti-Consensus Debate)
# ══════════════════════════════════════════════════════════════════════════════


def _precompute_expert_analysis(records: List[Dict]) -> Dict[str, object]:
    """预计算所有专家需要的统计数据，避免重复计算。"""
    if len(records) < 5:
        return {"ready": False}
    return {
        "ready": True,
        "hot_cold": analyze_hot_cold(records),
        "missing": analyze_missing(records),
        "cycle": analyze_cycle(records),
        "sum_trend": analyze_sum_trend(records),
        "zone": analyze_zone_balance(records),
    }


def _expert_evaluate_anti_consensus(
    agent: str,
    records: List[Dict],
    anti_balls: List[int],
    precomputed: Dict[str, object],
) -> Dict[int, float]:
    """专家用自己独特的策略视角评估反共识池中的球。

    每个专家基于相同的底层数据但用完全不同的公式打分，
    模拟"同一个事实、不同观点"的辩论场景。

    Returns:
        {ball: score} — 0.0~1.0 归一化分数，分数越高表示该专家越支持晋升此球。
    """
    if not precomputed.get("ready") or not anti_balls:
        return {b: 0.5 for b in anti_balls}

    hc = precomputed["hot_cold"]
    freq = hc["red_freq"]  # {ball: count}
    max_f = max(freq.values()) or 1

    if agent == "hot":
        # 趋势追随者：频率越高分越高
        return {b: freq.get(b, 0) / max_f for b in anti_balls}

    elif agent == "cold":
        # 价值逆向者：频率越低分越高（冷号反弹逻辑）
        return {b: 1.0 - freq.get(b, 0) / max_f for b in anti_balls}

    elif agent == "missing":
        # 回补猎手：遗漏期数越多分越高
        miss = precomputed["missing"]["red_missing"]
        max_m = max(miss.values()) or 1
        return {b: miss.get(b, 0) / max_m for b in anti_balls}

    elif agent == "cycle":
        # 周期信仰者：周期稳定性分
        cs = precomputed["cycle"].get("cycle_scores", {})
        max_c = max(cs.values()) or 1.0
        return {b: max(0.0, cs.get(b, 0.0)) / max(max_c, 0.01) for b in anti_balls}

    elif agent == "sum":
        # 均值回归者：和值贡献匹配度
        sw = precomputed["sum_trend"].get("sum_weights", {})
        return {b: sw.get(b, 0.3) for b in anti_balls}

    elif agent == "zone":
        # 结构主义者：区间需求度
        zw = precomputed["zone"].get("zone_weights", {})
        return {b: zw.get(b, 1.0) for b in anti_balls}

    elif agent == "balanced":
        # 中庸调和者：hot + cold + missing 三视角平均
        hot_s = _expert_evaluate_anti_consensus("hot", records, anti_balls, precomputed)
        cold_s = _expert_evaluate_anti_consensus("cold", records, anti_balls, precomputed)
        miss_s = _expert_evaluate_anti_consensus("missing", records, anti_balls, precomputed)
        return {b: (hot_s[b] + cold_s[b] + miss_s[b]) / 3.0 for b in anti_balls}

    elif agent == "random":
        # 混沌噪音源：提供随机扰动，防止所有专家同时忽略某个球
        # 使用确定性种子保证可复现
        seed_val = _stable_int_seed("anti-consensus-random", tuple(sorted(anti_balls)))
        rng = random.Random(seed_val)
        return {b: rng.random() for b in anti_balls}

    return {b: 0.5 for b in anti_balls}


def _build_debate_pool(
    snapshot: Dict[str, object],
    records: List[Dict],
    lead_model: Dict[str, Dict[str, float]],
    runtime_config: Optional[Dict[str, object]] = None,
    seed: Optional[int] = None,
) -> Dict[str, object]:
    """反共识辩论回合：让专家对反共识池进行二次评估，合并后重排名。

    流程：
    1. 识别反共识池（不在共识22球中的11个红球）
    2. 每个专家用自己独特的策略视角给反共识球打分
    3. 以 lead_model 权重聚合各专家辩论意见
    4. 合并共识分 + 辩论分，重新排名取前22
    5. 记录晋升/降级信息用于归档解释

    Returns:
        更新后的 snapshot（red_pool 可能变化）
    """
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    debate_factor = float(runtime.get("fusion_params", {}).get("debate_factor", 0.6))

    consensus_red = set(snapshot.get("red_pool", []))
    all_reds = set(range(1, 34))
    anti_reds = sorted(all_reds - consensus_red)  # 11 balls

    if not anti_reds:
        return snapshot

    # 预计算统计数据（所有专家共用）
    precomputed = _precompute_expert_analysis(records)

    # 每位专家对反共识球进行辩论评估
    anti_scores: Dict[int, float] = {b: 0.0 for b in anti_reds}
    total_weight = 0.0
    for agent in AGENT_TEAMS:
        agent_weight = float(lead_model.get("weights", {}).get(agent, 0.0))
        if agent_weight <= 0:
            continue
        total_weight += agent_weight
        agent_eval = _expert_evaluate_anti_consensus(agent, records, anti_reds, precomputed)
        for ball, score in agent_eval.items():
            anti_scores[ball] += score * agent_weight

    # 归一化辩论分
    if total_weight > 0:
        for ball in anti_reds:
            anti_scores[ball] /= total_weight

    # 合并：共识球保留原分，反共识球获得辩论分 × debate_factor
    merged_scores: Dict[int, float] = {}
    original_scores = snapshot.get("red_scores", {})

    # 共识球保留原有分数
    for ball in consensus_red:
        merged_scores[ball] = float(original_scores.get(ball, 0.0))

    # 反共识球：辩论分 × debate_factor（最高0.6，需要足够强才能进入前22）
    for ball in anti_reds:
        merged_scores[ball] = anti_scores[ball] * debate_factor

    # 重新排名，取前22
    ranked = sorted(merged_scores.items(), key=lambda item: (-item[1], item[0]))
    core_red_pool_size = int(runtime.get("pool_params", {}).get("core_red_pool_size", 22))
    new_red_pool = [ball for ball, score in ranked if score > 1e-8][:core_red_pool_size]

    # 确保池子达到目标大小
    if len(new_red_pool) < core_red_pool_size:
        for ball, _ in ranked:
            if ball not in new_red_pool:
                new_red_pool.append(ball)
            if len(new_red_pool) >= core_red_pool_size:
                break

    # ═══ 区间强制平衡：确保三区(1-11, 12-22, 23-33)各有足够代表 ═══
    zone_min = max(5, core_red_pool_size // 3 - 1)  # 每区至少7球(24池)或6球(22池)
    zones = {1: (1, 11), 2: (12, 22), 3: (23, 33)}
    for zone_id, (lo, hi) in zones.items():
        zone_in_pool = [b for b in new_red_pool if lo <= b <= hi]
        deficit = zone_min - len(zone_in_pool)
        if deficit <= 0:
            continue
        # 从该区间排名最高但未被选中的球中补充
        zone_candidates = [
            (b, merged_scores.get(b, 0.0))
            for b in range(lo, hi + 1)
            if b not in new_red_pool
        ]
        zone_candidates.sort(key=lambda x: -x[1])
        # 替换池中分数最低的非该区球
        non_zone_in_pool = [
            (b, merged_scores.get(b, 0.0))
            for b in new_red_pool if b < lo or b > hi
        ]
        non_zone_in_pool.sort(key=lambda x: x[1])
        for i in range(min(deficit, len(zone_candidates), len(non_zone_in_pool))):
            promoted_ball = zone_candidates[i][0]
            demoted_ball = non_zone_in_pool[i][0]
            new_red_pool.remove(demoted_ball)
            new_red_pool.append(promoted_ball)

    # 记录辩论结果
    promoted = sorted(set(new_red_pool) - consensus_red)
    demoted = sorted(consensus_red - set(new_red_pool))

    # 更新 snapshot
    snapshot["red_pool"] = new_red_pool
    snapshot["red_scores"] = {ball: round(float(merged_scores.get(ball, 0.0)), 6) for ball in new_red_pool}
    snapshot["red_scores_full"] = {
        ball: round(float(merged_scores.get(ball, 0.0)), 6)
        for ball in range(1, 34)
    }
    snapshot["debate_promoted"] = promoted
    snapshot["debate_demoted"] = demoted
    snapshot["debate_anti_scores"] = {ball: round(float(anti_scores.get(ball, 0.0)), 6) for ball in anti_reds}
    snapshot["debate_zone_balance"] = {
        str(zid): len([b for b in new_red_pool if lo <= b <= hi])
        for zid, (lo, hi) in zones.items()
    }

    return snapshot


def _build_blue_debate(
    snapshot: Dict[str, object],
    blue_engine: "BlueBallEngine",
    runtime_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Promote low-consensus blue balls with a standout engine dimension."""
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    pool_size = int(runtime.get("pool_params", {}).get("core_blue_pool_size", 10))
    full_scores = snapshot.get("blue_scores_full", {}) or snapshot.get("blue_scores", {})
    full_scores = {int(ball): float(score) for ball, score in full_scores.items()}
    if not full_scores:
        return snapshot

    consensus_pool = [int(ball) for ball in snapshot.get("blue_pool", [])][:pool_size]
    if not consensus_pool:
        consensus_pool = [ball for ball, _ in sorted(full_scores.items(), key=lambda item: item[1], reverse=True)[:pool_size]]
    anti_blues = [
        ball for ball, _ in sorted(full_scores.items(), key=lambda item: item[1], reverse=True)
        if ball not in consensus_pool
    ]
    if not anti_blues:
        return snapshot

    details = snapshot.get("blue_engine_details", {}) or {}
    if not details and blue_engine is not None:
        details = blue_engine.predict(pool_size=16).get("details", {}) or {}

    dimension_keys = ["amp_scores", "heat_scores"]
    # Different dimensions use different numeric scales. A fixed absolute
    # threshold would label ordinary heat scores as "standout". Use the third
    # highest value in each dimension as a relative cutoff instead.
    dimension_cutoffs = {}
    for key in dimension_keys:
        values = details.get(key, {}) or {}
        if isinstance(values, dict) and values:
            ranked_values = sorted((float(value) for value in values.values()), reverse=True)
            dimension_cutoffs[key] = ranked_values[min(2, len(ranked_values) - 1)]

    promoted = []
    for ball in anti_blues:
        missing_values = details.get("missing_scores", {}) or {}
        missing_score = float(missing_values.get(ball, 0.0)) if isinstance(missing_values, dict) else 0.0
        relative_standout = False
        for key, cutoff in dimension_cutoffs.items():
            values = details.get(key, {}) or {}
            if isinstance(values, dict) and float(values.get(ball, float("-inf"))) >= cutoff:
                relative_standout = True
                break
        if missing_score >= 2.0 or relative_standout:
            promoted.append(ball)
        if len(promoted) >= 2:
            break

    if not promoted:
        return snapshot

    demotion_order = sorted(consensus_pool, key=lambda ball: full_scores.get(ball, 0.0))
    demoted = demotion_order[:len(promoted)]
    new_pool = [ball for ball in consensus_pool if ball not in demoted] + promoted
    new_pool.sort(key=lambda ball: full_scores.get(ball, 0.0), reverse=True)
    snapshot["blue_pool"] = new_pool[:pool_size]
    snapshot["blue_scores"] = {ball: full_scores.get(ball, 0.0) for ball in snapshot["blue_pool"]}
    snapshot["blue_debate_promoted"] = promoted
    snapshot["blue_debate_demoted"] = demoted
    return snapshot



_OFFSET_EVIDENCE_AGENTS = ("hot", "cold", "missing", "cycle", "sum", "zone")


def _normalize_score_map(values: Dict[int, float], neutral: float = 0.5) -> Dict[int, float]:
    """Normalize a score map to 0..1 without inventing rank when all values tie."""
    if not values:
        return {}
    low = min(float(value) for value in values.values())
    high = max(float(value) for value in values.values())
    if high - low <= 1e-12:
        return {int(key): float(neutral) for key in values}
    return {
        int(key): (float(value) - low) / (high - low)
        for key, value in values.items()
    }


def _score_dispersion(values: List[float]) -> float:
    """Return a bounded 0..1 disagreement score for expert opinions."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return min(1.0, math.sqrt(variance) / 0.5)


def _build_offset_candidate_profiles(
    anti_candidates: List[int],
    records: List[Dict],
    lead_model: Dict[str, Dict[str, float]],
    snapshot: Dict[str, object],
    runtime_config: Optional[Dict[str, object]] = None,
) -> List[Dict[str, object]]:
    """Build explainable profiles for excluded reds with independent support.

    Balanced is derived from other views and random is intentionally noisy, so
    neither counts as independent evidence for a scientific offset candidate.
    """
    candidates = [
        int(ball)
        for ball in dict.fromkeys(anti_candidates)
        if 1 <= int(ball) <= 33
    ]
    if not candidates:
        return []

    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    fusion = runtime.get("fusion_params", {}) or {}
    candidate_limit = max(1, int(fusion.get("anti_ticket_candidate_limit", 6)))
    standout_threshold = float(fusion.get("anti_ticket_standout_threshold", 0.65))
    min_standout_agents = max(0, int(fusion.get("anti_ticket_min_standout_agents", 1)))

    precomputed = _precompute_expert_analysis(records)
    expert_scores: Dict[str, Dict[int, float]] = {}
    for agent in _OFFSET_EVIDENCE_AGENTS:
        evaluated = _expert_evaluate_anti_consensus(agent, records, candidates, precomputed)
        expert_scores[agent] = {
            ball: min(1.0, max(0.0, float(evaluated.get(ball, 0.0))))
            for ball in candidates
        }

    raw_prior = snapshot.get("red_scores_full", {}) or {}
    prior_values = {ball: float(raw_prior.get(ball, 0.0)) for ball in candidates}
    normalized_prior = _normalize_score_map(prior_values, neutral=0.0)
    lead_weights = lead_model.get("weights", {}) if isinstance(lead_model, dict) else {}
    evidence_weight_total = sum(max(0.0, float(lead_weights.get(agent, 0.0))) for agent in _OFFSET_EVIDENCE_AGENTS)

    profiles: List[Dict[str, object]] = []
    for ball in candidates:
        dimension_scores = {agent: expert_scores[agent][ball] for agent in _OFFSET_EVIDENCE_AGENTS}
        if evidence_weight_total > 0:
            weighted_support = sum(
                dimension_scores[agent] * max(0.0, float(lead_weights.get(agent, 0.0)))
                for agent in _OFFSET_EVIDENCE_AGENTS
            ) / evidence_weight_total
        else:
            weighted_support = sum(dimension_scores.values()) / len(_OFFSET_EVIDENCE_AGENTS)
        standout_agents = sorted(
            agent for agent, score in dimension_scores.items()
            if score >= standout_threshold
        )
        if len(standout_agents) < min_standout_agents:
            continue
        standout_ratio = len(standout_agents) / len(_OFFSET_EVIDENCE_AGENTS)
        disagreement = _score_dispersion(list(dimension_scores.values()))
        model_prior = normalized_prior.get(ball, 0.0)
        counter_evidence = (
            weighted_support * 0.50
            + standout_ratio * 0.25
            + disagreement * 0.15
            + model_prior * 0.10
        )
        reasons = [f"expert_support:{','.join(standout_agents)}"]
        if disagreement >= 0.35:
            reasons.append("expert_disagreement")
        if model_prior >= 0.5:
            reasons.append("model_prior_not_bottom")
        profiles.append(
            {
                "ball": ball,
                "counter_evidence": round(float(counter_evidence), 6),
                "weighted_support": round(float(weighted_support), 6),
                "standout_agents": standout_agents,
                "standout_ratio": round(float(standout_ratio), 6),
                "disagreement": round(float(disagreement), 6),
                "model_prior": round(float(model_prior), 6),
                "dimension_scores": {
                    agent: round(float(score), 6)
                    for agent, score in dimension_scores.items()
                },
                "reasons": reasons,
            }
        )

    profiles.sort(
        key=lambda row: (
            -float(row["counter_evidence"]),
            -len(row["standout_agents"]),
            int(row["ball"]),
        )
    )
    return profiles[:candidate_limit]


def _linear_quantile(values: List[float], quantile: float) -> float:
    """Return a deterministic linearly interpolated quantile."""
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    q = min(1.0, max(0.0, float(quantile)))
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _red_zone(ball: int) -> int:
    return min(3, max(1, (int(ball) - 1) // 11 + 1))


def _offset_structure_bounds(
    records: List[Dict],
    low_quantile: float,
    high_quantile: float,
) -> Tuple[float, float, float]:
    sums = [
        float(sum(int(ball) for ball in row.get("red_balls", []) or []))
        for row in records
        if len(row.get("red_balls", []) or []) == 6
    ]
    if not sums:
        return 21.0, 183.0, 102.0
    low = _linear_quantile(sums, low_quantile)
    high = _linear_quantile(sums, high_quantile)
    if high < low:
        low, high = high, low
    median = _linear_quantile(sums, 0.5)
    return low, high, median


def _select_scientific_offset_reds(
    base_reds: List[int],
    profiles: List[Dict[str, object]],
    red_scores: Dict[int, float],
    existing_tickets: List[Dict[str, object]],
    records: List[Dict],
    runtime_config: Optional[Dict[str, object]] = None,
    seed: Optional[int] = None,
    offset_count: Optional[int] = None,
) -> Optional[Dict[str, object]]:
    """Select one or two evidence-backed offset reds under structural constraints.

    ``offset_count`` is explicit for dynamic mode.  When omitted, the legacy
    fixed-scientific configuration value is used, preserving the old API.
    The selector deliberately returns enough diagnostics for an upstream
    policy to decide whether the evidence justifies 0/1/2 offsets.
    """
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    fusion = runtime.get("fusion_params", {}) or {}
    configured_count = int(fusion.get("anti_ticket_red_count", 2))
    anti_count = configured_count if offset_count is None else int(offset_count)
    anti_count = max(0, min(2, anti_count))

    base_ranked = sorted(
        dict.fromkeys(int(ball) for ball in base_reds if 1 <= int(ball) <= 33),
        key=lambda ball: (-float(red_scores.get(ball, 0.0)), ball),
    )
    keep_count = 6 - anti_count
    if len(base_ranked) < keep_count:
        return None
    kept_core = base_ranked[:keep_count]
    kept_set = set(kept_core)

    if anti_count == 0:
        return {
            "red": sorted(kept_core),
            "kept_core": sorted(kept_core),
            "offset_reds": [],
            "score": 0.0,
            "best_score": 0.0,
            "runner_up_score": 0.0,
            "score_gap": 0.0,
            "evidence_coverage": 0.0,
            "evidence_agent_count": 0,
            "score_breakdown": {
                "counter_evidence": 0.0,
                "coverage": 0.0,
                "structure": 1.0,
                "uncertainty": 0.0,
            },
            "score_weights": {},
            "constraints": {
                "zone_count": len({_red_zone(ball) for ball in kept_core}),
                "odd_count": sum(1 for ball in kept_core if ball % 2 == 1),
                "sum": sum(kept_core),
                "sum_low": None,
                "sum_high": None,
                "max_overlap": 0,
                "sum_relaxed": False,
            },
            "selected_profiles": [],
        }

    usable_profiles = [
        row for row in profiles
        if 1 <= int(row.get("ball", 0) or 0) <= 33
        and int(row.get("ball", 0) or 0) not in kept_set
    ]
    if len(usable_profiles) < anti_count:
        return None

    max_overlap = max(0, min(6, int(fusion.get("anti_ticket_max_overlap", 4))))
    low_q = float(fusion.get("anti_ticket_sum_quantile_low", 0.10))
    high_q = float(fusion.get("anti_ticket_sum_quantile_high", 0.90))
    sum_low, sum_high, sum_median = _offset_structure_bounds(records, low_q, high_q)
    configured_weights = fusion.get("anti_ticket_score_weights", {}) or {}
    weights = {
        "counter_evidence": float(configured_weights.get("counter_evidence", 0.35)),
        "coverage": float(configured_weights.get("coverage", 0.30)),
        "structure": float(configured_weights.get("structure", 0.20)),
        "uncertainty": float(configured_weights.get("uncertainty", 0.15)),
    }
    weight_total = sum(max(0.0, value) for value in weights.values()) or 1.0
    weights = {key: max(0.0, value) / weight_total for key, value in weights.items()}
    other_red_sets = [set(int(ball) for ball in ticket.get("red", []) or []) for ticket in existing_tickets]

    def evaluate_combination(rows: Tuple[Dict[str, object], ...], enforce_sum: bool) -> Optional[Dict[str, object]]:
        offset_reds = sorted(int(row["ball"]) for row in rows)
        final_reds = sorted(kept_core + offset_reds)
        if len(final_reds) != 6 or len(set(final_reds)) != 6:
            return None
        zone_count = len({_red_zone(ball) for ball in final_reds})
        odd_count = sum(1 for ball in final_reds if ball % 2 == 1)
        red_sum = sum(final_reds)
        overlaps = [len(set(final_reds) & other) for other in other_red_sets]
        max_actual_overlap = max(overlaps, default=0)
        if zone_count < 2 or not 2 <= odd_count <= 4 or max_actual_overlap > max_overlap:
            return None
        if enforce_sum and not sum_low <= red_sum <= sum_high:
            return None

        counter_evidence = sum(float(row.get("counter_evidence", 0.0)) for row in rows) / anti_count
        uncertainty = sum(float(row.get("disagreement", 0.0)) for row in rows) / anti_count
        evidence_agents = {
            str(agent)
            for row in rows
            for agent in row.get("standout_agents", []) or []
        }
        offset_zones = {_red_zone(ball) for ball in offset_reds}
        offset_zone_diversity = len(offset_zones) / 3.0
        numeric_spread = (max(offset_reds) - min(offset_reds)) / 32.0 if len(offset_reds) > 1 else 0.5
        evidence_coverage = len(evidence_agents) / len(_OFFSET_EVIDENCE_AGENTS)
        coverage = min(1.0, evidence_coverage * 0.50 + offset_zone_diversity * 0.30 + numeric_spread * 0.20)

        zone_quality = zone_count / 3.0
        parity_quality = max(0.0, 1.0 - abs(odd_count - 3) / 3.0)
        sum_radius = max(sum_high - sum_low, 1.0) / 2.0
        sum_quality = max(0.0, 1.0 - abs(red_sum - sum_median) / max(sum_radius, 1.0))
        structure = min(1.0, zone_quality * 0.40 + parity_quality * 0.30 + sum_quality * 0.30)
        breakdown = {
            "counter_evidence": round(counter_evidence, 6),
            "coverage": round(coverage, 6),
            "structure": round(structure, 6),
            "uncertainty": round(uncertainty, 6),
        }
        total_score = sum(breakdown[key] * weights[key] for key in weights)
        tie_break = _stable_int_seed("scientific-offset-combination", seed or 0, tuple(offset_reds))
        return {
            "red": final_reds,
            "kept_core": sorted(kept_core),
            "offset_reds": offset_reds,
            "score": round(float(total_score), 6),
            "score_breakdown": breakdown,
            "score_weights": {key: round(value, 6) for key, value in weights.items()},
            "evidence_coverage": round(evidence_coverage, 6),
            "evidence_agent_count": len(evidence_agents),
            "constraints": {
                "zone_count": zone_count,
                "odd_count": odd_count,
                "sum": red_sum,
                "sum_low": round(sum_low, 3),
                "sum_high": round(sum_high, 3),
                "max_overlap": max_actual_overlap,
                "sum_relaxed": not enforce_sum,
            },
            "selected_profiles": [dict(row) for row in rows],
            "_tie_break": tie_break,
        }

    evaluated: List[Dict[str, object]] = []
    for enforce_sum in (True, False):
        for combination in combinations(usable_profiles, anti_count):
            candidate = evaluate_combination(combination, enforce_sum=enforce_sum)
            if candidate is not None:
                evaluated.append(candidate)
        if evaluated:
            break
    if not evaluated:
        return None
    evaluated.sort(
        key=lambda row: (
            -float(row["score"]),
            int(row["_tie_break"]),
            tuple(row["offset_reds"]),
        )
    )
    selected = dict(evaluated[0])
    best_score = float(selected.get("score", 0.0))
    runner_up_score = float(evaluated[1].get("score", best_score)) if len(evaluated) > 1 else best_score
    selected["best_score"] = round(best_score, 6)
    selected["runner_up_score"] = round(runner_up_score, 6)
    selected["score_gap"] = round(max(0.0, best_score - runner_up_score), 6)
    selected.pop("_tie_break", None)
    return selected


def _choose_dynamic_offset_plan(
    selections: Dict[int, Optional[Dict[str, object]]],
    runtime_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Choose 0/1/2 offsets from precomputed scientific selections."""
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    fusion = runtime.get("fusion_params", {}) or {}
    one_threshold = float(fusion.get("anti_ticket_dynamic_one_score_threshold", 0.42))
    two_threshold = float(fusion.get("anti_ticket_dynamic_two_score_threshold", 0.58))
    min_gap = float(fusion.get("anti_ticket_dynamic_min_score_gap", 0.04))
    one_coverage = int(fusion.get("anti_ticket_dynamic_one_min_coverage", 1))
    two_coverage = int(fusion.get("anti_ticket_dynamic_two_min_coverage", 2))

    def _coverage(selection: Optional[Dict[str, object]]) -> int:
        if not selection:
            return 0
        if "evidence_agent_count" in selection:
            return int(selection.get("evidence_agent_count", 0) or 0)
        return int(round(float(selection.get("evidence_coverage", 0.0) or 0.0) * len(_OFFSET_EVIDENCE_AGENTS)))

    def _gap(selection: Optional[Dict[str, object]]) -> float:
        if not selection:
            return 0.0
        if "score_gap" in selection:
            return float(selection.get("score_gap", 0.0) or 0.0)
        return max(0.0, float(selection.get("best_score", selection.get("score", 0.0)) or 0.0) - float(selection.get("runner_up_score", 0.0) or 0.0))

    def _sum_relaxed(selection: Optional[Dict[str, object]]) -> bool:
        return bool((selection or {}).get("constraints", {}).get("sum_relaxed", False))

    two = selections.get(2)
    if two:
        two_score = float(two.get("best_score", two.get("score", 0.0)) or 0.0)
        if two_score >= two_threshold and _gap(two) >= min_gap and _coverage(two) >= two_coverage and not _sum_relaxed(two):
            return {"offset_count": 2, "selection": two, "reason": "two_offsets_high_confidence", "threshold": two_threshold, "score": round(two_score, 6), "score_gap": round(_gap(two), 6), "evidence_agent_count": _coverage(two)}

    one = selections.get(1)
    if one:
        one_score = float(one.get("best_score", one.get("score", 0.0)) or 0.0)
        if one_score >= one_threshold and _coverage(one) >= one_coverage:
            return {"offset_count": 1, "selection": one, "reason": "one_offset_base_confidence", "threshold": one_threshold, "score": round(one_score, 6), "score_gap": round(_gap(one), 6), "evidence_agent_count": _coverage(one)}

    return {"offset_count": 0, "selection": None, "reason": "no_sufficient_evidence", "threshold": one_threshold, "score": 0.0, "score_gap": 0.0, "evidence_agent_count": 0}


def _mix_anti_consensus_reds(
    base_reds: List[int],
    anti_candidates: List[int],
    red_scores: Dict[int, float],
    anti_count: int,
    rng: random.Random,
) -> List[int]:
    """Build a hybrid exploration row instead of discarding all model signal."""
    anti_count = max(0, min(6, int(anti_count)))
    keep_count = 6 - anti_count
    base_ranked = sorted(
        dict.fromkeys(int(ball) for ball in base_reds),
        key=lambda ball: float(red_scores.get(ball, 0.0)),
        reverse=True,
    )
    kept = base_ranked[:keep_count]
    pool = [int(ball) for ball in dict.fromkeys(anti_candidates) if int(ball) not in kept]
    selected = []
    while len(selected) < anti_count and pool:
        weights = [1.0 / (max(float(red_scores.get(ball, 0.0)), 0.0) + 0.1) for ball in pool]
        threshold = rng.random() * sum(weights)
        cumulative = 0.0
        for idx, weight in enumerate(weights):
            cumulative += weight
            if cumulative >= threshold:
                selected.append(pool.pop(idx))
                break
    if len(kept) + len(selected) < 6:
        fallback = [ball for ball in range(1, 34) if ball not in kept and ball not in selected]
        selected.extend(fallback[:6 - len(kept) - len(selected)])
    return sorted((kept + selected)[:6])


def generate_team_matrix_tickets(
    teams: Dict[str, Dict[str, object]],
    lead_model: Dict[str, Dict[str, float]],
    diff_factor: float,
    records: Optional[List[Dict]] = None,
    runtime_config: Optional[Dict[str, object]] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, object]]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    position_params = runtime.get("position_params", {}) or {}
    pos = analyze_positions(
        records,
        recent_periods=int(position_params.get("recent_periods", GLOBAL_CONFIG.position_analysis_periods)),
        min_weight=float(position_params.get("min_weight", GLOBAL_CONFIG.pos_weight_min)),
        max_weight=float(position_params.get("max_weight", GLOBAL_CONFIG.pos_weight_max)),
    ) if records else None
    pos_w = pos.get('pos_weights') if pos else None
    snapshot = build_core_pool_snapshot(
        teams, lead_model, diff_factor=diff_factor, runtime_config=runtime, pos_weights=pos_w
    )

    # --- 反共识辩论回合：专家对排除的球进行二次评估 ---
    if records and len(records) >= 10:
        snapshot = _build_debate_pool(snapshot, records, lead_model, runtime_config=runtime, seed=seed)
        promoted = snapshot.get("debate_promoted", [])
        demoted = snapshot.get("debate_demoted", [])
        if promoted or demoted:
            debate_detail = []
            if promoted:
                debate_detail.append(f"晋升 {len(promoted)} 球: {' '.join(f'{b:02d}' for b in promoted)}")
            if demoted:
                debate_detail.append(f"降级 {len(demoted)} 球: {' '.join(f'{b:02d}' for b in demoted)}")
            logger.info("辩论回合: %s", "; ".join(debate_detail))

    # --- 蓝球引擎：优先使用独立引擎，失败时回退到频率+遗漏甜点区 ---
    if records and len(records) >= 5:
        core_blue_pool_size = int(runtime.get("pool_params", {}).get("core_blue_pool_size", CORE_BLUE_POOL_SIZE))
        try:
            blue_engine = BlueBallEngine(records, config=_runtime_blue_params(runtime))
            blue_result = blue_engine.predict(pool_size=core_blue_pool_size)
            blue_scores_full = {
                int(b): round(float(score), 6)
                for b, score in blue_result.get("scores", {}).items()
                if 1 <= int(b) <= 16
            }
            blue_pool = [int(b) for b in blue_result.get("pool", []) if 1 <= int(b) <= 16][:core_blue_pool_size]
            snapshot["blue_pool"] = blue_pool
            snapshot["blue_scores"] = {b: blue_scores_full.get(b, 1.0) for b in blue_pool}
            snapshot["blue_scores_full"] = {b: blue_scores_full.get(b, 1.0) for b in range(1, 17)}
            snapshot["blue_engine_details"] = blue_result.get("details", {}) or {}
            snapshot = _build_blue_debate(snapshot, blue_engine, runtime_config=runtime)
        except Exception:
            blue_scores_simple, blue_pool_simple = _simple_blue_score(records)
            blue_pool = blue_pool_simple[:core_blue_pool_size]
            snapshot["blue_pool"] = blue_pool
            snapshot["blue_scores"] = {b: round(float(blue_scores_simple.get(b, 1.0)), 6) for b in blue_pool}
            snapshot["blue_scores_full"] = {b: round(float(blue_scores_simple.get(b, 1.0)), 6) for b in range(1, 17)}

    # --- 旋转矩阵出票 + 共现信念增强 + 反共识覆盖 ---
    matrix_snapshot = dict(snapshot)
    full_pool = list(snapshot.get("red_pool", []))
    full_scores = snapshot.get("red_scores_full", snapshot.get("red_scores", {}))
    matrix_snapshot["red_pool"] = full_pool[:22]
    matrix_snapshot["red_scores"] = {b: full_scores.get(b, 0.0) for b in full_pool[:22]}
    matrix_runtime = _deep_merge_dict(runtime, {"pool_params": {"core_red_pool_size": 22}})
    tickets = generate_rotation_matrix_tickets(matrix_snapshot, runtime_config=matrix_runtime, seed=seed)
    pair_cooc = _analyze_pairwise_cooccurrence(records, window=80) if records else None
    tickets = _apply_conviction_boost(tickets, snapshot, seed=seed, pair_cooccur=pair_cooc)

    # 反共识覆盖票：从模型排除的球中采样
    consensus_22 = set(full_pool[:22])
    all_33_set = set(range(1, 34))
    full_anti = sorted(all_33_set - consensus_22)

    fusion_params = runtime.get("fusion_params", {}) or {}
    anti_red_count = int(fusion_params.get("anti_ticket_red_count", 2))
    anti_strategy = str(fusion_params.get("anti_ticket_strategy", "scientific")).strip().lower()

    def _select_offset_blue(other_tickets: List[Dict[str, object]], rng: random.Random) -> int:
        used_blues = {int(ticket.get("blue", 0) or 0) for ticket in other_tickets}
        blue_pool = [int(ball) for ball in snapshot.get("blue_pool", []) or [] if 1 <= int(ball) <= 16]
        blue_scores_full = snapshot.get("blue_scores_full", snapshot.get("blue_scores", {})) or {}
        ranked = sorted(
            dict.fromkeys(blue_pool or range(1, 17)),
            key=lambda ball: (-float(blue_scores_full.get(ball, 0.0)), ball),
        )
        for ball in ranked:
            if ball not in used_blues:
                return ball
        if ranked:
            return ranked[0]
        return rng.randint(1, 16)

    def _build_legacy_anti_ticket(anti_idx: int, base_ticket: Dict[str, object]) -> Dict[str, object]:
        anti_candidates = list(full_anti)
        if len(anti_candidates) < anti_red_count:
            extra = sorted(consensus_22, key=lambda b: full_scores.get(b, 0.0))
            anti_candidates.extend(extra[:anti_red_count - len(anti_candidates)])
        anti_seed = seed or _stable_int_seed(f"anti-{anti_idx}", tuple(full_anti))
        rng_a = random.Random(anti_seed)
        anti_reds = _mix_anti_consensus_reds(
            list(base_ticket.get("red", [])),
            anti_candidates,
            full_scores,
            anti_count=anti_red_count,
            rng=rng_a,
        )
        bs_s, _ = _simple_blue_score(records) if records else ({}, [])
        existing_b = {ticket.get("blue", 0) for ticket in tickets}
        anti_blue = rng_a.randint(1, 16)
        if bs_s:
            for ball, _ in sorted(bs_s.items(), key=lambda item: -item[1]):
                if ball not in existing_b:
                    anti_blue = ball
                    break
        strategy = f"anti_hybrid_{anti_red_count}"
        return {
            "red": anti_reds,
            "blue": anti_blue,
            "sources": ["anti_consensus"],
            "explain": (
                f"反共识混合票{anti_idx + 1};探索红球数={anti_red_count};"
                f"红球={' '.join(f'{ball:02d}' for ball in anti_reds)};蓝球={anti_blue:02d}"
            ),
            "explain_json": {
                "sources": ["anti_consensus"],
                "strategy": strategy,
                "red": [
                    {
                        "ball": int(ball),
                        "top_agent": "anti" if ball in full_anti else "model",
                        "top_contribution": 0.0,
                        "agent_contributions": {},
                    }
                    for ball in anti_reds
                ],
                "blue": {
                    "ball": int(anti_blue),
                    "top_agent": "anti",
                    "top_contribution": 0.0,
                    "agent_contributions": {},
                },
                "core_pool": {"red_pool": full_anti},
                "diversity_replacements": [],
                "tier_strategy": strategy,
                "replaced_matrix_row_id": base_ticket.get("matrix_row_id"),
            },
            "diversity_replacements": [],
            "matrix_row_id": 5 + anti_idx + 1,
        }

    def _counterfactual_ticket(base_ticket: Dict[str, object]) -> Dict[str, object]:
        blue = int(base_ticket.get("blue", 0) or 0)
        return {
            "red": sorted(int(ball) for ball in base_ticket.get("red", []) or []),
            "blue": blue,
            "blue_score": float(base_ticket.get("blue_score", (snapshot.get("blue_scores_full", {}) or {}).get(blue, 0.0))),
            "matrix_row_id": int(base_ticket.get("matrix_row_id", 0) or 0),
        }

    def _build_scientific_offset_ticket(
        anti_idx: int,
        base_ticket: Dict[str, object],
        other_tickets: List[Dict[str, object]],
        offset_count: int,
        selection: Optional[Dict[str, object]] = None,
        strategy_prefix: str = "scientific",
        candidate_profiles: Optional[List[Dict[str, object]]] = None,
    ) -> Optional[Dict[str, object]]:
        profiles = candidate_profiles if candidate_profiles is not None else _build_offset_candidate_profiles(
            full_anti, records or [], lead_model, snapshot, runtime_config=runtime
        )
        if selection is None:
            selection = _select_scientific_offset_reds(
                list(base_ticket.get("red", [])), profiles, full_scores, existing_tickets=other_tickets, records=records or [], runtime_config=runtime, seed=seed, offset_count=offset_count
            )
        if not selection:
            return None
        offset_reds = set(int(ball) for ball in selection.get("offset_reds", []) or [])
        final_reds = [int(ball) for ball in selection.get("red", []) or []]
        if len(final_reds) != 6 or len(set(final_reds)) != 6 or len(offset_reds) != offset_count:
            return None
        rng = random.Random(seed or _stable_int_seed("scientific-offset-blue", tuple(final_reds)))
        blue = _select_offset_blue(other_tickets, rng)
        strategy = f"{strategy_prefix}_offset_{len(offset_reds)}"
        original_matrix = _counterfactual_ticket(base_ticket)
        red_agent_contrib = snapshot.get("red_agent_contrib", {}) or {}
        blue_score = float((snapshot.get("blue_scores_full", {}) or {}).get(blue, 0.0))
        offset_detail = {
            "candidate_profiles": profiles,
            "kept_core": list(selection.get("kept_core", [])),
            "selected_offset_reds": sorted(offset_reds),
            "score": float(selection.get("score", 0.0)),
            "best_score": float(selection.get("best_score", selection.get("score", 0.0))),
            "runner_up_score": float(selection.get("runner_up_score", selection.get("score", 0.0))),
            "score_gap": float(selection.get("score_gap", 0.0)),
            "evidence_coverage": float(selection.get("evidence_coverage", 0.0)),
            "evidence_agent_count": int(selection.get("evidence_agent_count", 0) or 0),
            "score_breakdown": dict(selection.get("score_breakdown", {})),
            "score_weights": dict(selection.get("score_weights", {})),
            "constraints": dict(selection.get("constraints", {})),
            "selected_profiles": list(selection.get("selected_profiles", [])),
            "replaced_matrix_row_id": base_ticket.get("matrix_row_id"),
        }
        return {
            "red": sorted(final_reds), "blue": blue, "blue_score": blue_score, "sources": ["scientific_offset"],
            "counterfactual_ticket": original_matrix,
            "explain": f"科学偏移票{anti_idx + 1};保留核心={' '.join(f'{ball:02d}' for ball in offset_detail['kept_core'])};偏移红球={' '.join(f'{ball:02d}' for ball in sorted(offset_reds))};组合分={float(selection.get('score', 0.0)):.3f};蓝球={blue:02d}",
            "explain_json": {
                "sources": ["scientific_offset"], "strategy": strategy,
                "red": [{"ball": int(ball), "top_agent": "offset" if ball in offset_reds else "model", "top_contribution": 0.0, "agent_contributions": {str(agent): round(float(value), 6) for agent, value in (red_agent_contrib.get(ball, {}) or {}).items()}} for ball in sorted(final_reds)],
                "blue": {"ball": int(blue), "blue_score": round(blue_score, 6), "top_agent": "blue_engine", "top_contribution": round(blue_score, 6), "agent_contributions": {}},
                "blue_score": round(blue_score, 6),
                "core_pool": {"red_pool": list(full_pool[:22]), "blue_pool": list(snapshot.get("blue_pool", []) or [])},
                "offset_strategy": offset_detail, "counterfactual_ticket": original_matrix, "diversity_replacements": [], "tier_strategy": strategy, "replaced_matrix_row_id": base_ticket.get("matrix_row_id"),
            },
            "diversity_replacements": [], "matrix_row_id": int(base_ticket.get("matrix_row_id", 0) or 0),
        }

    if len(tickets) >= 5:
        sorted_idx = sorted(
            range(len(tickets)),
            key=lambda index: sum(full_scores.get(ball, 0.0) for ball in tickets[index].get("red", []))
            / max(1, len(tickets[index].get("red", []))),
        )
        weakest_idx = sorted_idx[0]
        base_ticket = tickets[weakest_idx]
        other_tickets = [ticket for index, ticket in enumerate(tickets) if index != weakest_idx]
        replacement = None

        if anti_strategy == "dynamic":
            profiles = _build_offset_candidate_profiles(full_anti, records or [], lead_model, snapshot, runtime_config=runtime)
            selections = {
                count: _select_scientific_offset_reds(
                    list(base_ticket.get("red", [])), profiles, full_scores, existing_tickets=other_tickets,
                    records=records or [], runtime_config=runtime, seed=seed, offset_count=count,
                )
                for count in (1, 2)
            }
            plan = _choose_dynamic_offset_plan(selections, runtime_config=runtime)
            offset_count = int(plan.get("offset_count", 0) or 0)
            if offset_count:
                replacement = _build_scientific_offset_ticket(
                    0, base_ticket, other_tickets, offset_count=offset_count,
                    selection=plan.get("selection"), strategy_prefix="dynamic", candidate_profiles=profiles,
                )
                if replacement and isinstance(replacement.get("explain_json"), dict):
                    replacement["explain_json"]["dynamic_offset_plan"] = {key: value for key, value in plan.items() if key != "selection"}
            if replacement is None:
                original_matrix = _counterfactual_ticket(base_ticket)
                replacement = dict(base_ticket)
                replacement["red"] = list(original_matrix["red"])
                replacement["blue"] = original_matrix["blue"]
                replacement["blue_score"] = original_matrix["blue_score"]
                replacement["counterfactual_ticket"] = original_matrix
                explain_json = dict(replacement.get("explain_json") or {})
                explain_json.update({
                    "strategy": "dynamic_offset_0",
                    "tier_strategy": "dynamic_offset_0",
                    "counterfactual_ticket": original_matrix,
                    "dynamic_offset_plan": plan,
                    "blue_score": round(float(original_matrix["blue_score"]), 6),
                })
                replacement["explain_json"] = explain_json
                replacement["explain"] = f"动态科学偏移票1;偏移红球=无;保留原矩阵票;原因={plan.get('reason', 'no_sufficient_evidence')}"
                replacement["sources"] = list(dict.fromkeys(list(replacement.get("sources", []) or []) + ["dynamic_offset"]))
        elif anti_strategy == "scientific":
            replacement = _build_scientific_offset_ticket(
                0, base_ticket, other_tickets, offset_count=max(0, min(2, anti_red_count)),
            )
        if replacement is None:
            replacement = _build_legacy_anti_ticket(0, base_ticket)
        tickets.pop(weakest_idx)
        tickets.append(replacement)

    # Every final ticket exposes one comparable blue score for calibration.
    blue_scores_full = snapshot.get("blue_scores_full", snapshot.get("blue_scores", {})) or {}
    for ticket in tickets:
        blue = int(ticket.get("blue", 0) or 0)
        ticket["blue_score"] = float(ticket.get("blue_score", blue_scores_full.get(blue, 0.0)))
        explain_json = ticket.get("explain_json")
        if isinstance(explain_json, dict):
            explain_json["blue_score"] = round(float(ticket["blue_score"]), 6)


    return tickets[:5]


def _generate_stratified_tickets(
    snapshot: Dict[str, object],
    runtime_config: Optional[Dict[str, object]] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, object]]:
    """分层采样出票：信念票集中高分球，覆盖票聚焦反共识。

    将核心红球池按分数从高到低分为 4 层：
      - Tier 1 (Top 6):  最高共识分 → 信念票核心
      - Tier 2 (7-12):   次高共识分 → 信念票+平衡票
      - Tier 3 (13-18):  中等分（含辩论晋升球）→ 平衡票+覆盖票
      - Tier 4 (19-24):  低分/反共识 → 覆盖票核心

    5 张票分配：
      - 信念票 ×2: 从 Tier1+2 加权采样（高分球浓度高→最大化多红同框概率）
      - 平衡票 ×2: 从 Tier2+3 采样（覆盖中等分数区域）
      - 覆盖票 ×1: 从 Tier3+4 采样（含反共识晋升球，覆盖模型盲区）
    """
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    team_ticket_count = resolve_team_ticket_count(5)
    rng = random.Random(seed or _stable_int_seed("stratified", tuple(snapshot.get("red_pool", []))))

    red_pool = list(snapshot.get("red_pool", []))
    red_scores = snapshot.get("red_scores", {})
    blue_pool = list(snapshot.get("blue_pool", [])) or list(range(1, 17))
    blue_scores = snapshot.get("blue_scores", {})
    pool_sources = snapshot.get("pool_sources", {})
    blue_sources = snapshot.get("blue_sources", {})
    red_agent_contrib = snapshot.get("red_agent_contrib", {})
    blue_agent_contrib = snapshot.get("blue_agent_contrib", {})
    valid_agents = list(snapshot.get("valid_agents", []))
    debate_promoted = set(snapshot.get("debate_promoted", []))
    debate_demoted = set(snapshot.get("debate_demoted", []))

    if len(red_pool) < 12:
        # 池太小，回退到旋转矩阵
        return generate_rotation_matrix_tickets(snapshot, runtime_config=runtime, seed=seed)

    # 按分数排名分层
    ranked = sorted(red_pool, key=lambda b: red_scores.get(b, 0.0), reverse=True)
    n = len(ranked)
    tier_size = max(4, n // 4)
    tiers = [
        ranked[0:tier_size],
        ranked[tier_size:2 * tier_size],
        ranked[2 * tier_size:3 * tier_size],
        ranked[3 * tier_size:],
    ]
    # 合并短尾层
    tiers = [t for t in tiers if t]

    def _tier_sample(source_tiers: List[List[int]], k: int, concentration: float) -> List[int]:
        """从指定层中加权采样 k 个球。concentration 越高，高分球权重越大。"""
        candidates = []
        for tier_idx, tier in enumerate(source_tiers):
            # 越靠前的层权重越高
            tier_weight = math.exp(-tier_idx * concentration)
            for ball in tier:
                score = red_scores.get(ball, 0.5)
                candidates.append((ball, score * tier_weight))
        candidates.sort(key=lambda x: -x[1])
        # 加权不放回采样
        selected = []
        pool = list(candidates)
        while len(selected) < k and pool:
            weights = [w for _, w in pool]
            total_w = sum(weights) or 1.0
            r_val = rng.random() * total_w
            acc = 0.0
            picked_idx = len(pool) - 1
            for idx, (_, w) in enumerate(pool):
                acc += w
                if acc >= r_val:
                    picked_idx = idx
                    break
            selected.append(pool.pop(picked_idx)[0])
        return sorted(selected)

    def _select_blue_for_ticket(ticket_idx: int, used_blues: Set[int]) -> int:
        """选蓝球：优先引擎高分，确保5票蓝球去重覆盖。"""
        if not blue_pool:
            return rng.randint(1, 16)

        # 引擎分数归一化
        max_s = max(blue_scores.values()) or 1.0
        candidates = [(b, blue_scores.get(b, 0.5) / max_s) for b in blue_pool]

        # 优先未使用的高分蓝球（Top 3 中随机选，保留一定随机性）
        candidates.sort(key=lambda x: -x[1])
        unused = [(b, s) for b, s in candidates if b not in used_blues]
        if unused:
            top_n = min(3, len(unused))
            return rng.choice([b for b, _ in unused[:top_n]])

        return candidates[0][0]

    tickets: List[Dict[str, object]] = []
    used_blues: Set[int] = set()

    # 定义每张票的策略：(名称, 来源层, 浓度)
    # 共识模型有正向预测力，信念票聚焦顶部共识区
    strategies = [
        ("conviction_1", [0, 1], 1.5),   # 信念票1: Tier1+2(共识区), 高浓度
        ("conviction_2", [0, 1], 1.5),   # 信念票2: 同上→共识球密集→若模型对则多红同框
        ("balanced_1",  [1, 2], 0.8),    # 平衡票1: Tier2+3(中间区)
        ("balanced_2",  [1, 2], 0.8),    # 平衡票2
        ("coverage",    [2, 3], 0.3),    # 覆盖票: Tier3+4(反共识区)→确保模型盲区被覆盖
    ]

    for ticket_idx, (strat_name, tier_indices, concentration) in enumerate(strategies):
        source_tiers = [tiers[i] for i in tier_indices if i < len(tiers)]
        if not source_tiers:
            source_tiers = [tiers[0]]

        reds = _tier_sample(source_tiers, k=6, concentration=concentration)

        # 确保覆盖票中至少包含 2 个辩论晋升球
        if strat_name == "coverage" and len(debate_promoted) >= 2:
            promoted_in_ticket = [b for b in reds if b in debate_promoted]
            deficit = 2 - len(promoted_in_ticket)
            if deficit > 0:
                # 从未在票中的晋升球补充
                extra_promoted = [b for b in debate_promoted if b not in reds]
                rng.shuffle(extra_promoted)
                for _ in range(min(deficit, len(extra_promoted))):
                    # 替换票中非晋升球
                    non_promoted_idx = [
                        i for i, b in enumerate(reds) if b not in debate_promoted
                    ]
                    if non_promoted_idx and extra_promoted:
                        reds[non_promoted_idx[0]] = extra_promoted.pop(0)

        reds = sorted(reds)
        blue = _select_blue_for_ticket(ticket_idx, used_blues)
        used_blues.add(blue)

        # 构建解释信息
        source_agents = set()
        for b in reds:
            for agent in pool_sources.get(str(b), []):
                source_agents.add(agent)
        explain_parts = [f"来源Agent={','.join(sorted(source_agents)) if source_agents else 'stratified'}"]
        explain_parts.append(f"红球策略={strat_name}")
        explain_parts.append(f"蓝球贡献={blue:02d}:stratified")
        if debate_promoted:
            promoted_hits = [b for b in reds if b in debate_promoted]
            if promoted_hits:
                explain_parts.append(f"辩论晋升={','.join(f'{b:02d}' for b in promoted_hits)}")

        explain_json = {
            "sources": sorted(source_agents) or valid_agents,
            "strategy": strat_name,
            "red": [
                {
                    "ball": int(b),
                    "top_agent": max(
                        red_agent_contrib.get(b, {}).items(),
                        key=lambda x: x[1],
                        default=("unknown", 0.0),
                    )[0],
                    "top_contribution": round(float(max(
                        red_agent_contrib.get(b, {}).values(),
                        default=0.0,
                    )), 6),
                    "agent_contributions": {
                        a: round(float(c), 6)
                        for a, c in red_agent_contrib.get(b, {}).items()
                    },
                }
                for b in reds
            ],
            "blue": {
                "ball": int(blue),
                "top_agent": max(
                    blue_agent_contrib.get(blue, {}).items(),
                    key=lambda x: x[1],
                    default=("unknown", 0.0),
                )[0],
                "top_contribution": round(float(max(
                    blue_agent_contrib.get(blue, {}).values(),
                    default=0.0,
                )), 6),
                "agent_contributions": {
                    a: round(float(c), 6)
                    for a, c in blue_agent_contrib.get(blue, {}).items()
                },
            },
            "core_pool": {
                "red_pool": red_pool,
                "blue_pool": blue_pool,
                "debate_promoted": sorted(debate_promoted),
                "debate_demoted": sorted(debate_demoted),
            },
            "diversity_replacements": [],
            "tier_strategy": strat_name,
            "concentration": concentration,
        }

        tickets.append({
            "red": reds,
            "blue": blue,
            "sources": sorted(source_agents) or valid_agents,
            "valid_agents": valid_agents,
            "explain": ";".join(explain_parts),
            "explain_json": explain_json,
            "diversity_replacements": [],
            "matrix_row_id": ticket_idx + 1,
        })

    return tickets[:team_ticket_count]


def _apply_conviction_boost(
    tickets: List[Dict[str, object]],
    snapshot: Dict[str, object],
    seed: Optional[int] = None,
    pair_cooccur: Optional[Dict[int, List[int]]] = None,
) -> List[Dict[str, object]]:
    """信念增强：对平均分最高的票行进行浓度增强，优先选共现球。

    找到红球平均得分最高的那张票，将其中的低分球替换为
    池中高分球，优先选择与票内已有球共现频率高的球→直接提升多红同框概率。
    """
    if not tickets or len(tickets) < 2:
        return tickets

    red_scores = snapshot.get("red_scores", {})
    full_pool = list(snapshot.get("red_pool", []))
    if not red_scores or not full_pool:
        return tickets

    rng = random.Random(seed or _stable_int_seed("conviction-boost", tuple(full_pool)))

    def _cooc_score(candidate: int, existing: List[int]) -> float:
        """计算候选球与已有球的共现得分。"""
        if not pair_cooccur or candidate not in pair_cooccur:
            return 0.0
        partners = set(pair_cooccur.get(candidate, []))
        hits = sum(1 for b in existing if b in partners)
        return hits / max(1, len(existing))

    # 找平均分最高的票
    best_idx = 0
    best_avg = -1.0
    for i, t in enumerate(tickets):
        reds = t.get("red", [])
        if len(reds) != 6:
            continue
        avg = sum(red_scores.get(b, 0.0) for b in reds) / 6.0
        if avg > best_avg:
            best_avg = avg
            best_idx = i

    best_ticket = tickets[best_idx]
    best_reds = list(best_ticket.get("red", []))

    # 信念增强：替换最多2个低分球，优先共现球
    replacements = []
    for _ in range(2):
        current_reds = list(best_ticket.get("red", best_reds))
        min_score_in_ticket = min(red_scores.get(b, 0.0) for b in current_reds)
        min_ball = min(current_reds, key=lambda b: red_scores.get(b, 0.0))
        better_candidates = [
            b for b in full_pool
            if b not in current_reds and red_scores.get(b, 0.0) > min_score_in_ticket
        ]
        if not better_candidates:
            break
        # 综合评分：模型分(60%) + 共现分(40%)
        best_candidate = max(better_candidates, key=lambda b:
            red_scores.get(b, 0.0) * 0.6 + _cooc_score(b, current_reds) * 0.4
        )
        current_reds = [best_candidate if b == min_ball else b for b in current_reds]
        replacements.append((min_ball, best_candidate))
        best_ticket["red"] = sorted(current_reds)

    if replacements:
        boost_desc = ";".join(f"{new:02d}>{old:02d}" for old, new in replacements)
        best_ticket["explain"] = best_ticket.get("explain", "") + f";共现信念增强={boost_desc}"
        if "explain_json" in best_ticket and isinstance(best_ticket["explain_json"], dict):
            best_ticket["explain_json"]["conviction_boost"] = [
                {"replaced": old, "replacement": new} for old, new in replacements
            ]

    return tickets


def generate_final_team_tickets(
    teams: Dict[str, Dict[str, object]],
    lead_model: Dict[str, Dict[str, float]],
    diff_factor: float,
    records: Optional[List[Dict]] = None,
    runtime_config: Optional[Dict[str, object]] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, object]]:
    final_tickets = generate_team_matrix_tickets(
        teams,
        lead_model=lead_model,
        diff_factor=diff_factor,
        records=records,
        runtime_config=runtime_config,
        seed=seed,
    )
    if final_tickets:
        # 反共识辩论已在 generate_team_matrix_tickets 内部完成，
        # 不再追加独立随机探索票（反共识池已覆盖模型盲区）
        return final_tickets

    # 回退路径：generate_team_matrix_tickets 返回空时的兜底逻辑
    generated: List[Dict[str, object]] = []
    team_ticket_count = resolve_team_ticket_count(TEAM_TICKET_COUNT)
    fallback_rng = random.Random(seed)
    for i in range(team_ticket_count):
        final_ticket = judge_with_lead_agent(
            teams,
            lead_model=lead_model,
            diff_factor=diff_factor,
            ticket_index=i,
            seed=seed,
            existing_tickets=generated,
        )
        if not final_ticket:
            red, blue = generate_team_prediction(records or [], lead_model, rng=fallback_rng)
            final_ticket = {
                "red": red,
                "blue": blue,
                "sources": ["fallback"],
                "explain": "来源Agent=fallback;红球贡献=na;蓝球贡献=na;多样性替换=无",
                "explain_json": {
                    "sources": ["fallback"],
                    "red": [],
                    "blue": {
                        "ball": int(blue),
                        "top_agent": "fallback",
                        "top_contribution": 0.0,
                        "agent_contributions": {},
                    },
                    "diversity_replacements": [],
                },
            }
        generated.append(final_ticket)
    return generated


def _empty_multi_ticket_backtest_summary() -> Dict[str, float]:
    return {
        "samples": 0,
        "avg_ticket_score": 0.0,
        "best_of_5_avg_score": 0.0,
        "best_of_5_hit_rate_ge2": 0.0,
        "best_of_5_hit_rate_ge3": 0.0,
        "best_of_5_hit_rate_ge4": 0.0,
        "best_of_5_hit_rate_ge5": 0.0,
        "best_of_5_hit_rate_ge6": 0.0,
        "best_of_5_hit_count_4plus1": 0,
        "best_of_5_hit_rate_4plus1": 0.0,
        "best_of_5_hit_count_ge4_plus_blue": 0,
        "best_of_5_hit_rate_ge4_plus_blue": 0.0,
        "blue_pool_hit_rate": 0.0,
        "final_blue_hit_rate": 0.0,
        "avg_overlap": 0.0,
        "_ticket_count_total": 0.0,
        "_avg_ticket_score_total": 0.0,
        "_best_of_5_avg_score_total": 0.0,
        "_best_of_5_hit_rate_ge2_total": 0.0,
        "_best_of_5_hit_rate_ge3_total": 0.0,
        "_best_of_5_hit_rate_ge4_total": 0.0,
        "_best_of_5_hit_rate_ge5_total": 0.0,
        "_best_of_5_hit_rate_ge6_total": 0.0,
        "_best_of_5_hit_count_4plus1_total": 0.0,
        "_best_of_5_hit_count_ge4_plus_blue_total": 0.0,
        "_blue_pool_hit_rate_total": 0.0,
        "_final_blue_hit_rate_total": 0.0,
        "_avg_overlap_total": 0.0,
    }


def _average_ticket_overlap(tickets: List[Dict[str, object]]) -> float:
    if len(tickets) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for index, left in enumerate(tickets):
        left_red = set(left.get("red", []))
        for right in tickets[index + 1:]:
            total += len(left_red & set(right.get("red", [])))
            pairs += 1
    return total / max(pairs, 1)


def _extract_blue_pool_from_tickets(
    tickets: List[Dict[str, object]],
    fallback_blue_pool: Optional[List[int]] = None,
) -> List[int]:
    if fallback_blue_pool:
        return [int(ball) for ball in fallback_blue_pool]
    pool: Set[int] = set()
    for ticket in tickets:
        explain_json = ticket.get("explain_json") or {}
        if not isinstance(explain_json, dict):
            continue
        core_pool = explain_json.get("core_pool", {})
        if isinstance(core_pool, dict):
            for ball in core_pool.get("blue_pool", []) or []:
                if 1 <= int(ball) <= 16:
                    pool.add(int(ball))
        cover_strategy = explain_json.get("cover_strategy", {})
        if isinstance(cover_strategy, dict):
            for ball in cover_strategy.get("candidate_blue_pool", []) or []:
                if 1 <= int(ball) <= 16:
                    pool.add(int(ball))
    return sorted(pool)


def _accumulate_multi_ticket_backtest(
    summary: Dict[str, float],
    tickets: List[Dict[str, object]],
    target: Dict[str, object],
    fallback_blue_pool: Optional[List[int]] = None,
) -> None:
    if not tickets:
        return
    summary["samples"] += 1
    ticket_scores: List[float] = []
    red_hit_counts: List[int] = []
    blue_hit_any = False
    exact_4plus1_any = False
    ge4_plus_blue_any = False
    for ticket in tickets:
        red_hits = len(set(ticket.get("red", [])) & set(target.get("red_balls", [])))
        blue_hit = 1 if int(ticket.get("blue", 0) or 0) == int(target.get("blue_ball", 0) or 0) else 0
        score = _ticket_score(ticket.get("red", []), int(ticket.get("blue", 0) or 0), target)
        ticket_scores.append(score)
        red_hit_counts.append(red_hits)
        blue_hit_any = blue_hit_any or bool(blue_hit)
        exact_4plus1_any = exact_4plus1_any or (red_hits == 4 and bool(blue_hit))
        ge4_plus_blue_any = ge4_plus_blue_any or (red_hits >= 4 and bool(blue_hit))
    blue_pool = _extract_blue_pool_from_tickets(tickets, fallback_blue_pool=fallback_blue_pool)
    summary["_ticket_count_total"] += len(ticket_scores)
    summary["_avg_ticket_score_total"] += sum(ticket_scores)
    summary["_best_of_5_avg_score_total"] += max(ticket_scores)
    max_hits = max(red_hit_counts) if red_hit_counts else 0
    summary["_best_of_5_hit_rate_ge2_total"] += 1.0 if max_hits >= 2 else 0.0
    summary["_best_of_5_hit_rate_ge3_total"] += 1.0 if max_hits >= 3 else 0.0
    summary["_best_of_5_hit_rate_ge4_total"] += 1.0 if max_hits >= 4 else 0.0
    summary["_best_of_5_hit_rate_ge5_total"] += 1.0 if max_hits >= 5 else 0.0
    summary["_best_of_5_hit_rate_ge6_total"] += 1.0 if max_hits >= 6 else 0.0
    summary["_best_of_5_hit_count_4plus1_total"] += 1.0 if exact_4plus1_any else 0.0
    summary["_best_of_5_hit_count_ge4_plus_blue_total"] += 1.0 if ge4_plus_blue_any else 0.0
    summary["_blue_pool_hit_rate_total"] += 1.0 if int(target.get("blue_ball", 0) or 0) in blue_pool else 0.0
    summary["_final_blue_hit_rate_total"] += 1.0 if blue_hit_any else 0.0
    summary["_avg_overlap_total"] += _average_ticket_overlap(tickets)


def _finalize_multi_ticket_backtest(summary: Dict[str, float]) -> Dict[str, object]:
    samples = int(summary.get("samples", 0))
    if samples <= 0:
        return {
            "samples": 0,
            "avg_ticket_score": 0.0,
            "best_of_5_avg_score": 0.0,
            "best_of_5_hit_rate_ge2": 0.0,
            "best_of_5_hit_rate_ge3": 0.0,
            "best_of_5_hit_rate_ge4": 0.0,
            "best_of_5_hit_rate_ge5": 0.0,
            "best_of_5_hit_rate_ge6": 0.0,
            "best_of_5_hit_count_4plus1": 0,
            "best_of_5_hit_rate_4plus1": 0.0,
            "best_of_5_hit_count_ge4_plus_blue": 0,
            "best_of_5_hit_rate_ge4_plus_blue": 0.0,
            "blue_pool_hit_rate": 0.0,
            "final_blue_hit_rate": 0.0,
            "avg_overlap": 0.0,
        }
    ticket_count_total = max(float(summary.get("_ticket_count_total", 0.0)), 1.0)
    sample_total = float(samples)
    return {
        "samples": samples,
        "avg_ticket_score": round(float(summary.get("_avg_ticket_score_total", 0.0)) / ticket_count_total, 6),
        "best_of_5_avg_score": round(float(summary.get("_best_of_5_avg_score_total", 0.0)) / sample_total, 6),
        "best_of_5_hit_rate_ge2": round(float(summary.get("_best_of_5_hit_rate_ge2_total", 0.0)) / sample_total, 6),
        "best_of_5_hit_rate_ge3": round(float(summary.get("_best_of_5_hit_rate_ge3_total", 0.0)) / sample_total, 6),
        "best_of_5_hit_rate_ge4": round(float(summary.get("_best_of_5_hit_rate_ge4_total", 0.0)) / sample_total, 6),
        "best_of_5_hit_rate_ge5": round(float(summary.get("_best_of_5_hit_rate_ge5_total", 0.0)) / sample_total, 6),
        "best_of_5_hit_rate_ge6": round(float(summary.get("_best_of_5_hit_rate_ge6_total", 0.0)) / sample_total, 6),
        "best_of_5_hit_count_4plus1": int(summary.get("_best_of_5_hit_count_4plus1_total", 0.0)),
        "best_of_5_hit_rate_4plus1": round(float(summary.get("_best_of_5_hit_count_4plus1_total", 0.0)) / sample_total, 6),
        "best_of_5_hit_count_ge4_plus_blue": int(summary.get("_best_of_5_hit_count_ge4_plus_blue_total", 0.0)),
        "best_of_5_hit_rate_ge4_plus_blue": round(float(summary.get("_best_of_5_hit_count_ge4_plus_blue_total", 0.0)) / sample_total, 6),
        "blue_pool_hit_rate": round(float(summary.get("_blue_pool_hit_rate_total", 0.0)) / sample_total, 6),
        "final_blue_hit_rate": round(float(summary.get("_final_blue_hit_rate_total", 0.0)) / sample_total, 6),
        "avg_overlap": round(float(summary.get("_avg_overlap_total", 0.0)) / sample_total, 6),
    }


def _build_backtest_uplift(experiment: Dict[str, object], baseline: Dict[str, object]) -> Dict[str, float]:
    uplift: Dict[str, float] = {}
    for key in BACKTEST_UPLIFT_METRICS:
        experiment_value = float(experiment.get(key, 0.0))
        baseline_value = float(baseline.get(key, 0.0))
        if key == "avg_overlap":
            uplift[key] = round(baseline_value - experiment_value, 6)
        else:
            uplift[key] = round(experiment_value - baseline_value, 6)
    return uplift


def build_experiment_comparison_payload(
    team_cover_summary: Dict[str, object],
    team_summary: Dict[str, object],
    conditional_random_summary: Dict[str, object],
) -> Dict[str, Dict[str, float]]:
    return {
        "team_cover_vs_random_uplift": _build_backtest_uplift(team_cover_summary, conditional_random_summary),
        "team_vs_random_uplift": _build_backtest_uplift(team_summary, conditional_random_summary),
    }


def _build_three_way_backtest_comparison(
    team_cover_summary: Dict[str, object],
    team_summary: Dict[str, object],
    conditional_random_summary: Dict[str, object],
) -> Dict[str, Dict[str, float]]:
    return build_experiment_comparison_payload(
        team_cover_summary,
        team_summary,
        conditional_random_summary,
    )


def _pick_random_blue(
    preferred_numbers: List[int],
    used_blues: Set[int],
    rng: random.Random,
    allow_reuse: bool = False,
) -> Optional[int]:
    if not preferred_numbers:
        return None
    unused = [number for number in preferred_numbers if number not in used_blues]
    if unused:
        return rng.choice(unused)
    if allow_reuse:
        return rng.choice(preferred_numbers)
    return None


def _assign_conditional_random_blue(
    ticket_index: int,
    blue_buckets: Dict[str, List[int]],
    blue_ranked: List[int],
    used_blues: Set[int],
    rng: random.Random,
) -> Tuple[int, str]:
    bucket_order = ["main", "explore", "reversion", "main", "explore"]
    preferred_bucket = bucket_order[ticket_index % len(bucket_order)]
    pick = _pick_random_blue(list(blue_buckets.get(preferred_bucket, [])), used_blues, rng, allow_reuse=False)
    if pick is not None:
        return pick, preferred_bucket
    for fallback_bucket in ["main", "explore", "reversion"]:
        if fallback_bucket == preferred_bucket:
            continue
        pick = _pick_random_blue(list(blue_buckets.get(fallback_bucket, [])), used_blues, rng, allow_reuse=False)
        if pick is not None:
            return pick, fallback_bucket
    pick = _pick_random_blue(list(blue_ranked), used_blues, rng, allow_reuse=False)
    if pick is not None:
        return pick, "fallback"
    pick = _pick_random_blue(list(blue_buckets.get(preferred_bucket, [])), used_blues, rng, allow_reuse=True)
    if pick is not None:
        return pick, preferred_bucket
    pick = _pick_random_blue(list(blue_ranked), used_blues, rng, allow_reuse=True)
    if pick is not None:
        return pick, "fallback"
    return 1, "fallback"


def generate_conditional_random_tickets(
    snapshot: Dict[str, object],
    runtime_config: Optional[Dict[str, object]] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, object]]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    ticket_count = int(runtime.get("cover_mode", {}).get("ticket_count", TEAM_TICKET_COUNT))
    red_ranked = list(snapshot.get("red_ranked", []))
    blue_ranked = list(snapshot.get("blue_ranked", []))
    blue_scores = snapshot.get("blue_scores", {}) or {}
    blue_buckets = snapshot.get("blue_buckets", {}) or _build_cover_blue_buckets(
        blue_ranked,
        blue_scores,
        runtime_config=runtime,
    )
    candidate_pool_size = int(runtime.get("cover_mode", {}).get("candidate_pool_size", len(red_ranked)))
    if len(red_ranked) < 6:
        return []
    candidate_pool = list(red_ranked[:max(6, min(len(red_ranked), candidate_pool_size))])
    rng_seed = seed
    if rng_seed is None:
        rng_seed = _stable_int_seed("conditional-random", tuple(candidate_pool), tuple(blue_ranked))
    rng = random.Random(rng_seed)
    tickets: List[Dict[str, object]] = []
    used_blues: Set[int] = set()
    sample_attempts = max(12, min(64, len(candidate_pool) * 3))

    for ticket_index in range(ticket_count):
        best_red: Optional[List[int]] = None
        best_overlap: Optional[int] = None
        for _ in range(sample_attempts):
            combo_red = sorted(rng.sample(candidate_pool, 6))
            overlap = _max_cover_overlap(combo_red, tickets)
            if (
                best_red is None
                or overlap < (best_overlap if best_overlap is not None else 99)
                or (
                    overlap == (best_overlap if best_overlap is not None else 99)
                    and combo_red < best_red
                )
            ):
                best_red = combo_red
                best_overlap = overlap
            if overlap <= 4:
                break
        final_red = best_red or sorted(candidate_pool[:6])
        blue_ball, blue_bucket = _assign_conditional_random_blue(
            ticket_index,
            blue_buckets,
            blue_ranked,
            used_blues,
            rng,
        )
        used_blues.add(blue_ball)
        tickets.append(
            {
                "red": final_red,
                "blue": blue_ball,
                "sources": [CONDITIONAL_RANDOM_SOURCE],
                "explain": (
                    f"conditional_random_ticket={ticket_index + 1};"
                    f"blue_bucket={blue_bucket};blue={blue_ball:02d}"
                ),
                "explain_json": {
                    "cover_strategy": {
                        "mode": "conditional_random",
                        "ticket_index": ticket_index + 1,
                        "focus": "conditional-random",
                        "blue_bucket": blue_bucket,
                        "candidate_blue_pool": [int(n) for n in blue_ranked],
                        "blue_bucket_candidates": [int(n) for n in blue_buckets.get(blue_bucket, [])],
                        "selected_blue": int(blue_ball),
                        "max_overlap_with_previous": _max_cover_overlap(final_red, tickets),
                    }
                },
            }
        )
    return tickets


def conditional_random_backtest_report(
    records: List[Dict],
    cycles: int = 36,
    seed: Optional[int] = None,
    runtime_config: Optional[Dict[str, object]] = None,
    initial_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    samples = list(iterate_archived_cycles(records, cycles=cycles))
    summary = _empty_multi_ticket_backtest_summary()
    if not samples:
        return _finalize_multi_ticket_backtest(summary)
    lead_learning_cycles = max(8, min(12, cycles))
    lead_window_sizes = (lead_learning_cycles, max(lead_learning_cycles * 2, 24))
    for sample_index, (history_timeline, target) in enumerate(samples):
        history = list(reversed(history_timeline))
        sample_seed = _stable_int_seed("conditional-random-backtest", seed or 0, target.get("period", sample_index))
        lead_model = train_lead_agent(
            history,
            learning_cycles=min(lead_learning_cycles, len(history)),
            window_sizes=lead_window_sizes,
            initial_weights=initial_weights,
            num_trials=4,
        )
        expert_teams = build_expert_teams(history, tickets=resolve_team_ticket_count(TEAM_TICKET_COUNT), seed=sample_seed)
        snapshot = build_cover_candidate_snapshot(
            expert_teams,
            lead_model,
            diff_factor=1.0,
            records=history,
            runtime_config=runtime,
        )
        tickets = generate_conditional_random_tickets(snapshot, runtime_config=runtime, seed=sample_seed)
        _accumulate_multi_ticket_backtest(
            summary,
            tickets,
            target,
            fallback_blue_pool=list(snapshot.get("blue_ranked", [])),
        )
    return _finalize_multi_ticket_backtest(summary)


def team_cover_backtest_report(
    records: List[Dict],
    cycles: int = 36,
    seed: Optional[int] = None,
    runtime_config: Optional[Dict[str, object]] = None,
    initial_weights: Optional[Dict[str, float]] = None,
    progress_callback=None,
) -> Dict[str, object]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    samples = list(iterate_archived_cycles(records, cycles=cycles))
    summaries = {
        "team_cover": _empty_multi_ticket_backtest_summary(),
        "team": _empty_multi_ticket_backtest_summary(),
        "conditional_random": _empty_multi_ticket_backtest_summary(),
    }
    if not samples:
        finalized = {name: _finalize_multi_ticket_backtest(bucket) for name, bucket in summaries.items()}
        finalized["comparison"] = _build_three_way_backtest_comparison(
            finalized["team_cover"],
            finalized["team"],
            finalized["conditional_random"],
        )
        return finalized

    lead_learning_cycles = max(8, min(12, cycles))
    lead_window_sizes = (lead_learning_cycles, max(lead_learning_cycles * 2, 24))
    for sample_index, (history_timeline, target) in enumerate(samples):
        history = list(reversed(history_timeline))
        if progress_callback:
            progress_callback(
                {
                    "current": sample_index + 1,
                    "total": len(samples),
                    "period": str(target.get("period", "")),
                    "history_size": len(history),
                }
            )
        sample_seed = _stable_int_seed("team-cover-backtest", seed or 0, target.get("period", sample_index))
        lead_model = train_lead_agent(
            history,
            learning_cycles=min(lead_learning_cycles, len(history)),
            window_sizes=lead_window_sizes,
            initial_weights=initial_weights,
            num_trials=4,
        )
        expert_teams = build_expert_teams(history, tickets=resolve_team_ticket_count(TEAM_TICKET_COUNT), seed=sample_seed)
        team_tickets = generate_final_team_tickets(
            expert_teams,
            lead_model=lead_model,
            diff_factor=1.0,
            records=history,
            runtime_config=runtime,
            seed=sample_seed,
        )
        snapshot = build_cover_candidate_snapshot(
            expert_teams,
            lead_model,
            diff_factor=1.0,
            records=history,
            runtime_config=runtime,
        )
        team_cover_tickets = generate_team_cover_tickets(snapshot, runtime_config=runtime, seed=sample_seed)
        conditional_random_tickets = generate_conditional_random_tickets(
            snapshot,
            runtime_config=runtime,
            seed=sample_seed,
        )
        if not team_tickets or not team_cover_tickets or not conditional_random_tickets:
            continue
        _accumulate_multi_ticket_backtest(summaries["team"], team_tickets, target)
        _accumulate_multi_ticket_backtest(
            summaries["team_cover"],
            team_cover_tickets,
            target,
            fallback_blue_pool=list(snapshot.get("blue_ranked", [])),
        )
        _accumulate_multi_ticket_backtest(
            summaries["conditional_random"],
            conditional_random_tickets,
            target,
            fallback_blue_pool=list(snapshot.get("blue_ranked", [])),
        )

    finalized = {name: _finalize_multi_ticket_backtest(bucket) for name, bucket in summaries.items()}
    finalized["comparison"] = _build_three_way_backtest_comparison(
        finalized["team_cover"],
        finalized["team"],
        finalized["conditional_random"],
    )
    return finalized



def _empty_counterfactual_report() -> Dict[str, object]:
    return {
        "samples": 0,
        "offset_counts": {"0": 0, "1": 0, "2": 0},
        "offset_ticket_avg_score": 0.0,
        "original_matrix_ticket_avg_score": 0.0,
        "avg_score_delta": 0.0,
        "best_of_5_dynamic_avg_score": 0.0,
        "best_of_5_counterfactual_avg_score": 0.0,
        "best_of_5_avg_score_delta": 0.0,
        "improved": 0,
        "worse": 0,
        "tied": 0,
        "red_hit_delta": 0.0,
        "strategy_counts": {"dynamic_offset_0": 0, "dynamic_offset_1": 0, "dynamic_offset_2": 0},
    }


def _empty_blue_calibration_report() -> Dict[str, object]:
    return {
        "rank_buckets": {
            str(rank): {"exposures": 0, "hits": 0, "hit_rate": 0.0}
            for rank in range(1, 6)
        },
        "samples": 0,
        "top1_hit_rate": 0.0,
        "top3_hit_rate": 0.0,
        "hit_count": 0,
        "avg_hit_rank": 0.0,
        "high_rank_better_than_low": False,
    }


def _finalize_counterfactual_report(raw: Dict[str, object]) -> Dict[str, object]:
    report = _empty_counterfactual_report()
    report.update({key: value for key, value in raw.items() if key not in {"_offset_score_total", "_original_score_total", "_best_dynamic_total", "_best_counterfactual_total", "_red_hit_delta_total", "_best_delta_total"}})
    samples = int(raw.get("samples", 0) or 0)
    if samples <= 0:
        return report
    report["offset_ticket_avg_score"] = round(float(raw.get("_offset_score_total", 0.0)) / samples, 6)
    report["original_matrix_ticket_avg_score"] = round(float(raw.get("_original_score_total", 0.0)) / samples, 6)
    report["avg_score_delta"] = round(report["offset_ticket_avg_score"] - report["original_matrix_ticket_avg_score"], 6)
    report["best_of_5_dynamic_avg_score"] = round(float(raw.get("_best_dynamic_total", 0.0)) / samples, 6)
    report["best_of_5_counterfactual_avg_score"] = round(float(raw.get("_best_counterfactual_total", 0.0)) / samples, 6)
    report["best_of_5_avg_score_delta"] = round(float(raw.get("_best_delta_total", 0.0)) / samples, 6)
    report["red_hit_delta"] = round(float(raw.get("_red_hit_delta_total", 0.0)) / samples, 6)
    return report


def _finalize_blue_calibration_report(raw: Dict[str, object]) -> Dict[str, object]:
    report = _empty_blue_calibration_report()
    buckets = raw.get("rank_buckets", {}) or {}
    for rank in range(1, 6):
        bucket = buckets.get(rank, buckets.get(str(rank), {})) or {}
        exposures = int(bucket.get("exposures", 0) or 0)
        hits = int(bucket.get("hits", 0) or 0)
        report["rank_buckets"][str(rank)] = {"exposures": exposures, "hits": hits, "hit_rate": round(hits / exposures, 6) if exposures else 0.0}
    samples = int(raw.get("samples", 0) or 0)
    hit_count = int(raw.get("hit_count", 0) or 0)
    report["samples"] = samples
    report["hit_count"] = hit_count
    report["top1_hit_rate"] = round(int(raw.get("top1_hits", 0) or 0) / samples, 6) if samples else 0.0
    report["top3_hit_rate"] = round(int(raw.get("top3_hits", 0) or 0) / samples, 6) if samples else 0.0
    report["avg_hit_rank"] = round(float(raw.get("hit_rank_total", 0.0)) / hit_count, 6) if hit_count else 0.0
    high = sum(report["rank_buckets"][str(rank)]["hit_rate"] for rank in (1, 2)) / 2.0
    low = sum(report["rank_buckets"][str(rank)]["hit_rate"] for rank in (4, 5)) / 2.0
    report["high_rank_better_than_low"] = high > low
    return report


def _stability_objective(overall: Dict[str, object]) -> float:
    """Fixed comparison score; it is not a probability estimate."""
    best_score = min(1.0, max(0.0, float(overall.get("best_of_5_avg_score", 0.0)) / 7.5))
    overlap_penalty = max(0.0, float(overall.get("avg_overlap", 0.0)) - 3.0) * 0.01
    return round(
        float(overall.get("best_of_5_hit_rate_ge2", 0.0)) * 0.15
        + float(overall.get("best_of_5_hit_rate_ge3", 0.0)) * 0.30
        + float(overall.get("best_of_5_hit_rate_ge4", 0.0)) * 0.30
        + float(overall.get("final_blue_hit_rate", 0.0)) * 0.10
        + best_score * 0.15
        - overlap_penalty,
        6,
    )


def _percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    q = min(1.0, max(0.0, float(quantile)))
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _bootstrap_mean_ci(values: List[float], iterations: int = 1000) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1 or iterations <= 0:
        mean = sum(values) / len(values)
        return mean, mean
    seed = _stable_int_seed("stability-bootstrap", *(f"{value:.12g}" for value in values), iterations)
    rng = random.Random(seed)
    size = len(values)
    means = []
    for _ in range(iterations):
        means.append(sum(values[rng.randrange(size)] for _ in range(size)) / size)
    return _percentile(means, 0.025), _percentile(means, 0.975)


def _stability_stats(values: List[float], bootstrap_iterations: int = 1000) -> Dict[str, object]:
    numeric = [float(value) for value in values]
    if not numeric:
        return {
            "samples": 0,
            "mean": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "median": 0.0,
            "q25": 0.0,
            "q75": 0.0,
            "ci95_low": 0.0,
            "ci95_high": 0.0,
        }
    mean = sum(numeric) / len(numeric)
    variance = sum((value - mean) ** 2 for value in numeric) / len(numeric)
    ci_low, ci_high = _bootstrap_mean_ci(numeric, iterations=bootstrap_iterations)
    return {
        "samples": len(numeric),
        "mean": round(mean, 6),
        "std": round(math.sqrt(variance), 6),
        "min": round(min(numeric), 6),
        "max": round(max(numeric), 6),
        "median": round(_percentile(numeric, 0.5), 6),
        "q25": round(_percentile(numeric, 0.25), 6),
        "q75": round(_percentile(numeric, 0.75), 6),
        "ci95_low": round(ci_low, 6),
        "ci95_high": round(ci_high, 6),
    }


def _paired_outcome_summary(deltas: List[float]) -> Dict[str, object]:
    tolerance = 1e-12
    positive = sum(1 for value in deltas if value > tolerance)
    negative = sum(1 for value in deltas if value < -tolerance)
    tied = len(deltas) - positive - negative
    return {
        "objective_delta": _stability_stats(deltas),
        "dynamic_positive_ratio": round(positive / len(deltas), 6) if deltas else 0.0,
        "positive_count": positive,
        "negative_count": negative,
        "tie_count": tied,
    }


def _group_stability_runs(runs: List[Dict[str, object]], group_key: str) -> Dict[str, object]:
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for run in runs:
        grouped[str(run.get(group_key, ""))].append(run)
    result: Dict[str, object] = {}
    for key, group in grouped.items():
        dynamic_values = [float(run.get("dynamic_objective", 0.0)) for run in group]
        legacy_values = [float(run.get("legacy_objective", 0.0)) for run in group]
        deltas = [float(run.get("objective_delta", 0.0)) for run in group]
        result[key] = {
            "dynamic_objective": _stability_stats(dynamic_values),
            "legacy_objective": _stability_stats(legacy_values),
            "paired": _paired_outcome_summary(deltas),
        }
    return result


def team_stability_backtest_report(
    records: List[Dict],
    windows: Iterable[int] = (36, 72, 108, 144),
    seeds: Iterable[int] = (7, 42, 101, 202, 777, 2026),
    runtime_config: Optional[Dict[str, object]] = None,
    initial_weights: Optional[Dict[str, float]] = None,
    progress_callback=None,
) -> Dict[str, object]:
    """Run paired dynamic-vs-legacy clean backtests without writing archives."""
    windows = tuple(dict.fromkeys(max(1, int(window)) for window in windows))
    seeds = tuple(dict.fromkeys(int(seed) for seed in seeds))
    clean_runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    runs: List[Dict[str, object]] = []
    context_cache = BacktestContextCache(max_entries=2)
    metric_names = (
        "objective",
        "best_of_5_avg_score",
        "best_of_5_hit_rate_ge2",
        "best_of_5_hit_rate_ge3",
        "best_of_5_hit_rate_ge4",
        "final_blue_hit_rate",
        "avg_overlap",
    )
    total = len(windows) * len(seeds)
    current = 0
    for window in windows:
        for seed in seeds:
            current += 1
            if progress_callback:
                progress_callback({"current": current, "total": total, "window": window, "seed": seed})
            dynamic_runtime = _deep_merge_dict(clean_runtime, {"fusion_params": {"anti_ticket_strategy": "dynamic"}})
            legacy_runtime = _deep_merge_dict(clean_runtime, {"fusion_params": {"anti_ticket_strategy": "legacy"}})
            dynamic = team_matrix_backtest_report(
                records, cycles=window, seed=seed, runtime_config=dynamic_runtime,
                initial_weights=initial_weights, context_cache=context_cache,
            )
            legacy = team_matrix_backtest_report(
                records, cycles=window, seed=seed, runtime_config=legacy_runtime,
                initial_weights=initial_weights, context_cache=context_cache,
            )
            dynamic_overall = dynamic.get("overall", {})
            legacy_overall = legacy.get("overall", {})
            dynamic_objective = _stability_objective(dynamic_overall)
            legacy_objective = _stability_objective(legacy_overall)
            runs.append({
                "window": window,
                "seed": seed,
                "dynamic": dynamic,
                "legacy": legacy,
                "dynamic_objective": dynamic_objective,
                "legacy_objective": legacy_objective,
                "objective_delta": round(dynamic_objective - legacy_objective, 6),
            })

    aggregate: Dict[str, object] = {}
    for mode in ("dynamic", "legacy"):
        values: Dict[str, List[float]] = {name: [] for name in metric_names}
        for run in runs:
            overall = run[mode].get("overall", {})
            values["objective"].append(float(run[f"{mode}_objective"]))
            for name in metric_names[1:]:
                values[name].append(float(overall.get(name, 0.0)))
        aggregate[mode] = {name: _stability_stats(vals) for name, vals in values.items()}
        aggregate[mode]["robust_score"] = round(
            aggregate[mode]["objective"]["mean"] - 0.5 * aggregate[mode]["objective"]["std"], 6
        )
    deltas = [float(run["objective_delta"]) for run in runs]
    aggregate["paired"] = _paired_outcome_summary(deltas)
    aggregate["by_window"] = _group_stability_runs(runs, "window")
    aggregate["by_seed"] = _group_stability_runs(runs, "seed")
    return {
        "report_schema_version": "stability-report/v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "windows": list(windows),
        "seeds": list(seeds),
        "runs": runs,
        "aggregate": aggregate,
        "context_cache": {"enabled": True, **context_cache.snapshot()},
        "guardrails": {
            "no_archive_write": True,
            "fixed_ticket_count": 5,
            "posthoc_tuning": False,
            "objective_is_comparison_only": True,
        },
    }


def _flatten_scalar_paths(value: object, prefix: str = "") -> List[Tuple[str, object]]:
    rows: List[Tuple[str, object]] = []
    if isinstance(value, dict):
        for key in sorted(value):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_scalar_paths(value[key], child_prefix))
    elif isinstance(value, (str, int, float, bool)) or value is None:
        rows.append((prefix, value))
    return rows


def export_backtest_report(report: Dict[str, object], export_prefix: str) -> Dict[str, str]:
    """Write a nested report as JSON plus compact run and summary CSV files."""
    prefix = os.path.abspath(os.path.expanduser(str(export_prefix)))
    parent = os.path.dirname(prefix)
    if parent:
        os.makedirs(parent, exist_ok=True)
    paths = {
        "json": f"{prefix}.json",
        "runs_csv": f"{prefix}.runs.csv",
        "summary_csv": f"{prefix}.summary.csv",
    }
    with open(paths["json"], "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)

    source_rows = report.get("runs") or report.get("folds") or []
    flat_rows: List[Dict[str, object]] = []
    for source in source_rows:
        if not isinstance(source, dict):
            continue
        row: Dict[str, object] = {}
        for path, scalar in _flatten_scalar_paths(source):
            if path.startswith("dynamic.") or path.startswith("legacy."):
                continue
            row[path] = scalar
        flat_rows.append(row)
    fieldnames = sorted({key for row in flat_rows for key in row})
    with open(paths["runs_csv"], "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["report_schema_version"])
        writer.writeheader()
        if flat_rows:
            writer.writerows(flat_rows)

    summary_rows = [
        {"path": path, "value": scalar}
        for path, scalar in _flatten_scalar_paths(report.get("aggregate", {}), "aggregate")
    ]
    with open(paths["summary_csv"], "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "value"])
        writer.writeheader()
        writer.writerows(summary_rows)
    return paths


def _threshold_values(values: Iterable[float], name: str, minimum: float = 0.0) -> Tuple[float, ...]:
    cleaned = tuple(dict.fromkeys(round(float(value), 6) for value in values))
    if not cleaned:
        raise ValueError(f"{name} must contain at least one value")
    if any(value < minimum for value in cleaned):
        raise ValueError(f"{name} values must be >= {minimum}")
    return cleaned


def _build_threshold_candidates(
    runtime_config: Optional[Dict[str, object]] = None,
    one_thresholds: Iterable[float] = (0.38, 0.42, 0.46),
    two_thresholds: Iterable[float] = (0.54, 0.58, 0.62),
    gap_thresholds: Iterable[float] = (0.02, 0.04, 0.06),
    grid_mode: str = "one_factor",
) -> List[Dict[str, float]]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    fusion = runtime.get("fusion_params", {}) or {}
    base = (
        round(float(fusion.get("anti_ticket_dynamic_one_score_threshold", 0.42)), 6),
        round(float(fusion.get("anti_ticket_dynamic_two_score_threshold", 0.58)), 6),
        round(float(fusion.get("anti_ticket_dynamic_min_score_gap", 0.04)), 6),
    )
    ones = _threshold_values(one_thresholds, "one_thresholds")
    twos = _threshold_values(two_thresholds, "two_thresholds")
    gaps = _threshold_values(gap_thresholds, "gap_thresholds")
    if grid_mode == "cartesian":
        raw = list(product(ones, twos, gaps))
    elif grid_mode == "one_factor":
        raw = [base]
        raw.extend((value, base[1], base[2]) for value in ones)
        raw.extend((base[0], value, base[2]) for value in twos)
        raw.extend((base[0], base[1], value) for value in gaps)
    else:
        raise ValueError("grid_mode must be 'one_factor' or 'cartesian'")
    candidates: List[Dict[str, float]] = []
    seen = set()
    for one_score, two_score, min_gap in raw:
        key = (round(float(one_score), 6), round(float(two_score), 6), round(float(min_gap), 6))
        if key in seen or key[1] < key[0]:
            continue
        seen.add(key)
        candidates.append({
            "one_score_threshold": key[0],
            "two_score_threshold": key[1],
            "min_score_gap": key[2],
        })
    if not candidates:
        raise ValueError("threshold grid produced no valid candidates")
    return candidates


def _build_rolling_calibration_folds(
    records: List[Dict],
    train_cycles: int = 36,
    validation_cycles: int = 12,
    fold_count: int = 3,
    min_history: int = 30,
) -> List[Dict[str, object]]:
    train_cycles = max(1, int(train_cycles))
    validation_cycles = max(1, int(validation_cycles))
    fold_count = max(1, int(fold_count))
    min_history = max(1, int(min_history))
    timeline = list(reversed(records))
    minimum_train_end = min_history + train_cycles
    first_train_end = max(minimum_train_end, len(timeline) - fold_count * validation_cycles)
    available_folds = max(0, (len(timeline) - first_train_end) // validation_cycles)
    actual_folds = min(fold_count, available_folds)
    folds: List[Dict[str, object]] = []
    for index in range(actual_folds):
        train_end = first_train_end + index * validation_cycles
        validation_end = train_end + validation_cycles
        train_timeline = timeline[:train_end]
        validation_targets = timeline[train_end:validation_end]
        validation_context = timeline[:validation_end]
        folds.append({
            "fold": index + 1,
            "train_records": list(reversed(train_timeline)),
            "validation_records": list(reversed(validation_context)),
            "validation_targets": list(validation_targets),
            "train_end_period": str(train_timeline[-1].get("period", "")),
            "validation_start_period": str(validation_targets[0].get("period", "")),
            "validation_end_period": str(validation_targets[-1].get("period", "")),
        })
    return folds


def _runtime_with_thresholds(
    runtime_config: Dict[str, object], thresholds: Dict[str, float], strategy: str = "dynamic"
) -> Dict[str, object]:
    return _deep_merge_dict(runtime_config, {"fusion_params": {
        "anti_ticket_strategy": strategy,
        "anti_ticket_dynamic_one_score_threshold": float(thresholds["one_score_threshold"]),
        "anti_ticket_dynamic_two_score_threshold": float(thresholds["two_score_threshold"]),
        "anti_ticket_dynamic_min_score_gap": float(thresholds["min_score_gap"]),
    }})


def team_threshold_calibration_report(
    records: List[Dict],
    train_cycles: int = 36,
    validation_cycles: int = 12,
    fold_count: int = 3,
    seeds: Iterable[int] = (42,),
    runtime_config: Optional[Dict[str, object]] = None,
    initial_weights: Optional[Dict[str, float]] = None,
    one_thresholds: Iterable[float] = (0.38, 0.42, 0.46),
    two_thresholds: Iterable[float] = (0.54, 0.58, 0.62),
    gap_thresholds: Iterable[float] = (0.02, 0.04, 0.06),
    grid_mode: str = "one_factor",
    evaluator=None,
    progress_callback=None,
) -> Dict[str, object]:
    """Select thresholds on older prefixes and evaluate on unseen next blocks."""
    base_runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    seeds = tuple(dict.fromkeys(int(seed) for seed in seeds))
    if not seeds:
        raise ValueError("calibration requires at least one seed")
    candidates = _build_threshold_candidates(
        base_runtime, one_thresholds, two_thresholds, gap_thresholds, grid_mode=grid_mode
    )
    folds = _build_rolling_calibration_folds(
        records, train_cycles=train_cycles, validation_cycles=validation_cycles, fold_count=fold_count
    )
    evaluate = evaluator or team_matrix_backtest_report
    context_cache = BacktestContextCache(max_entries=4) if evaluator is None else None
    cache: Dict[Tuple[object, ...], Dict[str, object]] = {}
    cache_hits = 0
    cache_misses = 0

    def cached_eval(eval_records: List[Dict], cycles: int, seed: int, runtime: Dict[str, object]) -> Dict[str, object]:
        nonlocal cache_hits, cache_misses
        period_key = tuple(str(row.get("period", "")) for row in eval_records)
        runtime_key = json.dumps(runtime, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = (period_key, int(cycles), int(seed), runtime_key)
        if key in cache:
            cache_hits += 1
            return cache[key]
        cache_misses += 1
        kwargs = {
            "cycles": int(cycles),
            "seed": int(seed),
            "runtime_config": runtime,
            "initial_weights": initial_weights,
        }
        if context_cache is not None:
            kwargs["context_cache"] = context_cache
        cache[key] = evaluate(eval_records, **kwargs)
        return cache[key]

    base_fusion = base_runtime.get("fusion_params", {}) or {}
    default_thresholds = {
        "one_score_threshold": float(base_fusion.get("anti_ticket_dynamic_one_score_threshold", 0.42)),
        "two_score_threshold": float(base_fusion.get("anti_ticket_dynamic_two_score_threshold", 0.58)),
        "min_score_gap": float(base_fusion.get("anti_ticket_dynamic_min_score_gap", 0.04)),
    }
    total = len(folds) * (len(candidates) * len(seeds) + 3 * len(seeds))
    current = 0
    fold_reports: List[Dict[str, object]] = []
    selected_counts: Counter = Counter()
    for fold in folds:
        candidate_rows = []
        for candidate in candidates:
            runtime = _runtime_with_thresholds(base_runtime, candidate, strategy="dynamic")
            objectives = []
            for seed in seeds:
                current += 1
                if progress_callback:
                    progress_callback({"current": current, "total": total, "fold": fold["fold"], "phase": "train"})
                result = cached_eval(fold["train_records"], train_cycles, seed, runtime)
                objectives.append(_stability_objective(result.get("overall", {})))
            stats = _stability_stats(objectives, bootstrap_iterations=0)
            robust_score = round(float(stats["mean"]) - 0.5 * float(stats["std"]), 6)
            distance = sum(abs(float(candidate[key]) - float(default_thresholds[key])) for key in default_thresholds)
            candidate_rows.append({
                "thresholds": candidate,
                "objective": stats,
                "robust_score": robust_score,
                "distance_from_default": round(distance, 6),
            })
        selected_row = max(
            candidate_rows,
            key=lambda row: (float(row["robust_score"]), float(row["objective"]["mean"]), -float(row["distance_from_default"])),
        )
        selected = selected_row["thresholds"]
        selected_key = json.dumps(selected, sort_keys=True, separators=(",", ":"))
        selected_counts[selected_key] += 1

        selected_runtime = _runtime_with_thresholds(base_runtime, selected, strategy="dynamic")
        default_runtime = _runtime_with_thresholds(base_runtime, default_thresholds, strategy="dynamic")
        legacy_runtime = _runtime_with_thresholds(base_runtime, default_thresholds, strategy="legacy")
        # Re-read the selected training reports through the memoizer so cache use is observable.
        selected_training_objectives = [
            _stability_objective(cached_eval(fold["train_records"], train_cycles, seed, selected_runtime).get("overall", {}))
            for seed in seeds
        ]
        validation_values = {"selected": [], "default_dynamic": [], "legacy": []}
        for seed in seeds:
            for label, runtime in (
                ("selected", selected_runtime),
                ("default_dynamic", default_runtime),
                ("legacy", legacy_runtime),
            ):
                current += 1
                if progress_callback:
                    progress_callback({"current": current, "total": total, "fold": fold["fold"], "phase": "validation", "mode": label})
                result = cached_eval(fold["validation_records"], len(fold["validation_targets"]), seed, runtime)
                validation_values[label].append(_stability_objective(result.get("overall", {})))
        validation_stats = {
            label: _stability_stats(values, bootstrap_iterations=0)
            for label, values in validation_values.items()
        }
        selected_mean = float(validation_stats["selected"]["mean"])
        default_mean = float(validation_stats["default_dynamic"]["mean"])
        legacy_mean = float(validation_stats["legacy"]["mean"])
        fold_reports.append({
            "fold": fold["fold"],
            "train_end_period": fold["train_end_period"],
            "validation_start_period": fold["validation_start_period"],
            "validation_end_period": fold["validation_end_period"],
            "train_samples": int(train_cycles),
            "validation_samples": len(fold["validation_targets"]),
            "selected_thresholds": dict(selected),
            "selected_training_objective": _stability_stats(selected_training_objectives, bootstrap_iterations=0),
            "candidate_ranking": sorted(candidate_rows, key=lambda row: (-float(row["robust_score"]), float(row["distance_from_default"]))),
            "validation": validation_stats,
            "selected_vs_default_delta": round(selected_mean - default_mean, 6),
            "selected_vs_legacy_delta": round(selected_mean - legacy_mean, 6),
        })

    default_deltas = [float(fold["selected_vs_default_delta"]) for fold in fold_reports]
    legacy_deltas = [float(fold["selected_vs_legacy_delta"]) for fold in fold_reports]
    selection_frequency = []
    for key, count in selected_counts.most_common():
        selection_frequency.append({"thresholds": json.loads(key), "count": count, "ratio": round(count / len(fold_reports), 6) if fold_reports else 0.0})
    return {
        "report_schema_version": "threshold-calibration/v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "train_cycles": int(train_cycles),
        "validation_cycles": int(validation_cycles),
        "fold_count_requested": int(fold_count),
        "seeds": list(seeds),
        "grid_mode": grid_mode,
        "candidates": candidates,
        "folds": fold_reports,
        "aggregate": {
            "selected_vs_default_delta": _stability_stats(default_deltas),
            "selected_vs_legacy_delta": _stability_stats(legacy_deltas),
            "selection_frequency": selection_frequency,
        },
        "cache": {"entries": len(cache), "hits": cache_hits, "misses": cache_misses},
        "context_cache": ({"enabled": True, **context_cache.snapshot()} if context_cache is not None else {"enabled": False}),
        "guardrails": {
            "expanding_window": True,
            "future_data_in_training": False,
            "no_archive_write": True,
            "objective_is_comparison_only": True,
        },
    }


def _context_cache_telemetry(context_cache: Optional[BacktestContextCache]) -> Dict[str, object]:
    if context_cache is None:
        return {"enabled": False}
    return {"enabled": True, **context_cache.snapshot()}


def _prepare_team_backtest_contexts(
    records: List[Dict],
    cycles: int,
    seed: Optional[int],
    initial_weights: Optional[Dict[str, float]],
    context_cache: Optional[BacktestContextCache],
) -> List[Dict[str, object]]:
    ticket_count = resolve_team_ticket_count(TEAM_TICKET_COUNT)

    def prepare() -> List[Dict[str, object]]:
        raw_samples = list(iterate_archived_cycles(records, cycles=cycles))
        lead_learning_cycles = max(8, min(12, cycles))
        lead_window_sizes = (lead_learning_cycles, max(lead_learning_cycles * 2, 24))
        contexts: List[Dict[str, object]] = []
        for sample_index, (history_timeline, target) in enumerate(raw_samples):
            history = list(reversed(history_timeline))
            sample_seed = _stable_int_seed("team-backtest", seed or 0, target.get("period", sample_index))
            lead_model = train_lead_agent(
                history,
                learning_cycles=min(lead_learning_cycles, len(history)),
                window_sizes=lead_window_sizes,
                initial_weights=initial_weights,
                num_trials=4,
            )
            expert_teams = build_expert_teams(history, tickets=ticket_count, seed=sample_seed)
            contexts.append({
                "history": history,
                "target": target,
                "sample_seed": sample_seed,
                "lead_model": lead_model,
                "expert_teams": expert_teams,
            })
        return contexts

    if context_cache is None:
        return prepare()
    key = make_backtest_context_key(records, cycles, seed, initial_weights, ticket_count)
    return context_cache.get_or_prepare(key, prepare)


def team_matrix_backtest_report(
    records: List[Dict],
    cycles: int = 36,
    seed: Optional[int] = None,
    runtime_config: Optional[Dict[str, object]] = None,
    initial_weights: Optional[Dict[str, float]] = None,
    progress_callback=None,
    context_cache: Optional[BacktestContextCache] = None,
) -> Dict[str, object]:
    runtime = _deep_merge_dict(DEFAULT_RUNTIME_CONFIG, runtime_config or {})
    samples = _prepare_team_backtest_contexts(records, cycles, seed, initial_weights, context_cache)
    if not samples:
        return {
            "overall": {
                "samples": 0,
                "avg_ticket_score": 0.0,
                "best_of_5_avg_score": 0.0,
                "best_of_5_hit_rate_ge2": 0.0,
                "best_of_5_hit_rate_ge3": 0.0,
                "best_of_5_hit_count_4plus1": 0,
                "best_of_5_hit_rate_4plus1": 0.0,
                "best_of_5_hit_count_ge4_plus_blue": 0,
                "best_of_5_hit_rate_ge4_plus_blue": 0.0,
                "blue_pool_hit_rate": 0.0,
                "final_blue_hit_rate": 0.0,
                "avg_overlap": 0.0,
            },
            "matrix_rows": [],
            "counterfactual": _empty_counterfactual_report(),
            "blue_calibration": _empty_blue_calibration_report(),
            "context_cache": _context_cache_telemetry(context_cache),
        }

    overall = {
        "samples": len(samples),
        "avg_ticket_score": 0.0,
        "best_of_5_avg_score": 0.0,
        "best_of_5_hit_rate_ge2": 0.0,
        "best_of_5_hit_rate_ge3": 0.0,
        "best_of_5_hit_rate_ge4": 0.0,
        "best_of_5_hit_rate_ge5": 0.0,
        "best_of_5_hit_rate_ge6": 0.0,
        "best_of_5_hit_count_4plus1": 0,
        "best_of_5_hit_rate_4plus1": 0.0,
        "best_of_5_hit_count_ge4_plus_blue": 0,
        "best_of_5_hit_rate_ge4_plus_blue": 0.0,
        "blue_pool_hit_rate": 0.0,
        "final_blue_hit_rate": 0.0,
        "avg_overlap": 0.0,
    }
    matrix_rows: Dict[int, Dict[str, float]] = {}
    counterfactual_raw = _empty_counterfactual_report()
    counterfactual_raw.update({"_offset_score_total": 0.0, "_original_score_total": 0.0, "_best_dynamic_total": 0.0, "_best_counterfactual_total": 0.0, "_red_hit_delta_total": 0.0, "_best_delta_total": 0.0})
    blue_calibration_raw = {
        "rank_buckets": {rank: {"exposures": 0, "hits": 0} for rank in range(1, 6)},
        "samples": 0, "top1_hits": 0, "top3_hits": 0, "hit_count": 0, "hit_rank_total": 0.0,
    }
    ticket_count_total = 0

    for sample_index, context in enumerate(samples):
        history = context["history"]
        target = context["target"]
        sample_seed = int(context["sample_seed"])
        lead_model = context["lead_model"]
        expert_teams = context["expert_teams"]
        if progress_callback:
            progress_callback(
                {
                    "current": sample_index + 1,
                    "total": len(samples),
                    "period": str(target.get("period", "")),
                    "history_size": len(history),
                }
            )
        diff_factor = 1.0
        tickets = generate_final_team_tickets(
            expert_teams,
            lead_model=lead_model,
            diff_factor=diff_factor,
            records=history,
            runtime_config=runtime,
            seed=sample_seed,
        )
        if not tickets:
            continue

        ticket_scores = []
        red_hit_counts = []
        ticket_evaluations: List[Tuple[Dict[str, object], float, int]] = []
        blue_hit_any = False
        exact_4plus1_any = False
        ge4_plus_blue_any = False
        blue_pool_hit = False

        for ticket in tickets:
            red_hits = len(set(ticket["red"]) & set(target["red_balls"]))
            blue_hit = 1 if ticket["blue"] == target["blue_ball"] else 0
            score = _ticket_score(ticket["red"], ticket["blue"], target)
            ticket_scores.append(score)
            red_hit_counts.append(red_hits)
            ticket_evaluations.append((ticket, score, red_hits))
            blue_hit_any = blue_hit_any or bool(blue_hit)
            exact_4plus1_any = exact_4plus1_any or (red_hits == 4 and bool(blue_hit))
            ge4_plus_blue_any = ge4_plus_blue_any or (red_hits >= 4 and bool(blue_hit))
            ticket_count_total += 1

            explain_json = ticket.get("explain_json") or {}
            core_pool = explain_json.get("core_pool", {}) if isinstance(explain_json, dict) else {}
            blue_pool = core_pool.get("blue_pool", []) if isinstance(core_pool, dict) else []
            if target["blue_ball"] in blue_pool:
                blue_pool_hit = True

            row_id = int(ticket.get("matrix_row_id", 0) or 0)
            if row_id:
                bucket = matrix_rows.setdefault(row_id, {"row_id": row_id, "samples": 0.0, "score_total": 0.0})
                bucket["samples"] += 1.0
                bucket["score_total"] += score

        if not ticket_scores:
            continue

        # Blue calibration ranks the distinct final blue balls by one unified score.
        distinct_blue: Dict[int, Tuple[Dict[str, object], float, int]] = {}
        for evaluation in ticket_evaluations:
            blue = int(evaluation[0].get("blue", 0) or 0)
            current = distinct_blue.get(blue)
            if current is None or float(evaluation[0].get("blue_score", 0.0)) > float(current[0].get("blue_score", 0.0)):
                distinct_blue[blue] = evaluation
        ranked_blues = sorted(distinct_blue.values(), key=lambda item: (-float(item[0].get("blue_score", 0.0)), int(item[0].get("blue", 0) or 0)))[:5]
        blue_calibration_raw["samples"] += 1
        actual_blue = int(target.get("blue_ball", 0) or 0)
        for rank, (ticket, _, _) in enumerate(ranked_blues, start=1):
            bucket = blue_calibration_raw["rank_buckets"][rank]
            bucket["exposures"] += 1
            if int(ticket.get("blue", 0) or 0) == actual_blue:
                bucket["hits"] += 1
                blue_calibration_raw["hit_count"] += 1
                blue_calibration_raw["hit_rank_total"] += rank
                if rank == 1:
                    blue_calibration_raw["top1_hits"] += 1
                if rank <= 3:
                    blue_calibration_raw["top3_hits"] += 1

        # Compare the dynamic fifth ticket with the untouched weakest matrix row.
        for eval_index, (ticket, selected_score, selected_red_hits) in enumerate(ticket_evaluations):
            explain_json = ticket.get("explain_json") or {}
            strategy = str(explain_json.get("strategy", "")) if isinstance(explain_json, dict) else ""
            original = ticket.get("counterfactual_ticket")
            if not strategy.startswith("dynamic_offset_") or not isinstance(original, dict):
                continue
            try:
                offset_count = int(strategy.rsplit("_", 1)[-1])
            except ValueError:
                offset_count = 0
            offset_count = max(0, min(2, offset_count))
            original_score = _ticket_score(original.get("red", []), int(original.get("blue", 0) or 0), target)
            original_red_hits = len(set(original.get("red", [])) & set(target.get("red_balls", [])))
            counterfactual_scores = list(ticket_scores)
            counterfactual_scores[eval_index] = original_score
            best_dynamic = max(ticket_scores)
            best_counterfactual = max(counterfactual_scores)
            delta = selected_score - original_score
            counterfactual_raw["samples"] += 1
            counterfactual_raw["offset_counts"][str(offset_count)] += 1
            counterfactual_raw["strategy_counts"][f"dynamic_offset_{offset_count}"] += 1
            counterfactual_raw["_offset_score_total"] += selected_score
            counterfactual_raw["_original_score_total"] += original_score
            counterfactual_raw["_best_dynamic_total"] += best_dynamic
            counterfactual_raw["_best_counterfactual_total"] += best_counterfactual
            counterfactual_raw["_best_delta_total"] += best_dynamic - best_counterfactual
            counterfactual_raw["_red_hit_delta_total"] += selected_red_hits - original_red_hits
            if delta > 1e-12:
                counterfactual_raw["improved"] += 1
            elif delta < -1e-12:
                counterfactual_raw["worse"] += 1
            else:
                counterfactual_raw["tied"] += 1
            break

        max_hits = max(red_hit_counts) if red_hit_counts else 0
        overall["avg_ticket_score"] += sum(ticket_scores)
        overall["best_of_5_avg_score"] += max(ticket_scores)
        overall["best_of_5_hit_rate_ge2"] += 1.0 if max_hits >= 2 else 0.0
        overall["best_of_5_hit_rate_ge3"] += 1.0 if max_hits >= 3 else 0.0
        overall["best_of_5_hit_rate_ge4"] += 1.0 if max_hits >= 4 else 0.0
        overall["best_of_5_hit_rate_ge5"] += 1.0 if max_hits >= 5 else 0.0
        overall["best_of_5_hit_rate_ge6"] += 1.0 if max_hits >= 6 else 0.0
        overall["best_of_5_hit_count_4plus1"] += 1 if exact_4plus1_any else 0
        overall["best_of_5_hit_count_ge4_plus_blue"] += 1 if ge4_plus_blue_any else 0
        overall["blue_pool_hit_rate"] += 1.0 if blue_pool_hit else 0.0
        overall["final_blue_hit_rate"] += 1.0 if blue_hit_any else 0.0
        overall["avg_overlap"] += _average_ticket_overlap(tickets)

    sample_count = max(1, int(overall["samples"]))
    overall["avg_ticket_score"] = round(overall["avg_ticket_score"] / max(ticket_count_total, 1), 6)
    overall["best_of_5_avg_score"] = round(overall["best_of_5_avg_score"] / sample_count, 6)
    overall["best_of_5_hit_rate_ge2"] = round(overall["best_of_5_hit_rate_ge2"] / sample_count, 6)
    overall["best_of_5_hit_rate_ge3"] = round(overall["best_of_5_hit_rate_ge3"] / sample_count, 6)
    overall["best_of_5_hit_rate_ge4"] = round(overall["best_of_5_hit_rate_ge4"] / sample_count, 6)
    overall["best_of_5_hit_rate_ge5"] = round(overall["best_of_5_hit_rate_ge5"] / sample_count, 6)
    overall["best_of_5_hit_rate_ge6"] = round(overall["best_of_5_hit_rate_ge6"] / sample_count, 6)
    overall["best_of_5_hit_rate_4plus1"] = round(overall["best_of_5_hit_count_4plus1"] / sample_count, 6)
    overall["best_of_5_hit_rate_ge4_plus_blue"] = round(overall["best_of_5_hit_count_ge4_plus_blue"] / sample_count, 6)
    overall["blue_pool_hit_rate"] = round(overall["blue_pool_hit_rate"] / sample_count, 6)
    overall["final_blue_hit_rate"] = round(overall["final_blue_hit_rate"] / sample_count, 6)
    overall["avg_overlap"] = round(overall["avg_overlap"] / sample_count, 6)

    matrix_row_report = []
    for bucket in matrix_rows.values():
        samples_count = max(bucket["samples"], 1.0)
        matrix_row_report.append(
            {
                "row_id": int(bucket["row_id"]),
                "samples": int(bucket["samples"]),
                "avg_score": round(bucket["score_total"] / samples_count, 6),
            }
        )
    matrix_row_report.sort(key=lambda row: (-row["avg_score"], row["row_id"]))
    return {
        "overall": overall,
        "matrix_rows": matrix_row_report,
        "counterfactual": _finalize_counterfactual_report(counterfactual_raw),
        "blue_calibration": _finalize_blue_calibration_report(blue_calibration_raw),
        "context_cache": _context_cache_telemetry(context_cache),
    }


def judge_with_lead_agent(
    teams: Dict[str, Dict[str, object]],
    lead_model: Dict[str, Dict[str, float]],
    diff_factor: float,
    ticket_index: int,
    seed: Optional[int],
    existing_tickets: Optional[List[Dict[str, object]]] = None,
) -> Optional[Dict[str, object]]:
    red_scores = {i: 0.0 for i in range(1, 34)}
    blue_scores = {i: 0.0 for i in range(1, 17)}
    red_sources, blue_sources = _ball_sources(teams, ticket_index)
    valid_agents: List[str] = []
    red_agent_contrib: Dict[int, Dict[str, float]] = {i: {} for i in range(1, 34)}
    blue_agent_contrib: Dict[int, Dict[str, float]] = {i: {} for i in range(1, 17)}

    for agent, payload in teams.items():
        proposals = payload.get("proposals", [])
        if ticket_index >= len(proposals):
            continue
        proposal = proposals[ticket_index]
        valid_agents.append(agent)
        base_weight = lead_model["weights"].get(agent, 0.0) * diff_factor
        diff_bonus = max(0.0, lead_model["diff_scores"].get(agent, 0.0)) * 0.2
        final_weight = base_weight * (1 + diff_bonus)
        for red in proposal["red"]:
            agreement_bonus = len(red_sources.get(red, [])) * 0.08
            contribution = final_weight * (1 + agreement_bonus)
            red_scores[red] += contribution
            red_agent_contrib[red][agent] = red_agent_contrib[red].get(agent, 0.0) + contribution
        blue = proposal["blue"]
        agreement_bonus = len(blue_sources.get(blue, [])) * 0.1
        contribution = final_weight * (1 + agreement_bonus)
        blue_scores[blue] += contribution
        blue_agent_contrib[blue][agent] = blue_agent_contrib[blue].get(agent, 0.0) + contribution

    if not valid_agents:
        return None
    rng = random.Random((seed or random.randint(1, 999999)) + ticket_index * 17)
    diversified_scores = dict(red_scores)
    existing_tickets = existing_tickets or []
    for ticket in existing_tickets:
        reds = ticket.get("red", [])
        for ball in reds:
            diversified_scores[ball] = diversified_scores.get(ball, 0.0) * 0.62
    final_red = _weighted_unique_sample(diversified_scores, 6, rng)
    diversity_replacements: List[str] = []
    if existing_tickets:
        attempts = 0
        while attempts < 4 and any(len(set(final_red) & set(t.get("red", []))) > 4 for t in existing_tickets):
            overlap_counts = Counter()
            for ticket in existing_tickets:
                overlap = set(final_red) & set(ticket.get("red", []))
                for ball in overlap:
                    overlap_counts[ball] += 1
            if not overlap_counts:
                break
            drop_ball = max(overlap_counts.items(), key=lambda x: x[1])[0]
            candidates = [n for n in range(1, 34) if n not in final_red]
            candidates.sort(
                key=lambda n: (
                    sum(1 for t in existing_tickets if n in t.get("red", [])),
                    -diversified_scores.get(n, 0.0),
                )
            )
            if candidates:
                old_ball = drop_ball
                new_ball = candidates[0]
                final_red.remove(drop_ball)
                final_red.append(new_ball)
                final_red = sorted(set(final_red))
                while len(final_red) < 6:
                    refill = next((n for n in range(1, 34) if n not in final_red), None)
                    if refill is None:
                        break
                    final_red.append(refill)
                final_red = sorted(final_red[:6])
                diversity_replacements.append(f"{old_ball:02d}->{new_ball:02d}")
            attempts += 1
    final_blue = _weighted_choice(blue_scores, rng)
    source_agents = sorted(set(red_sources.get(ball, [])[0] for ball in final_red if red_sources.get(ball)))
    if final_blue in blue_sources:
        source_agents.extend(blue_sources[final_blue])
    source_agents = sorted(set(source_agents))
    red_contrib_parts = []
    red_contrib_json = []
    for ball in final_red:
        contribs = red_agent_contrib.get(ball, {})
        top_agent, top_score = ("na", 0.0)
        if contribs:
            top_agent, top_score = max(contribs.items(), key=lambda x: x[1])
        red_contrib_parts.append(f"{ball:02d}:{top_agent}({top_score:.3f})")
        red_contrib_json.append(
            {
                "ball": int(ball),
                "top_agent": top_agent,
                "top_contribution": round(float(top_score), 6),
                "agent_contributions": {
                    a: round(float(s), 6) for a, s in sorted(contribs.items(), key=lambda x: x[1], reverse=True)
                },
            }
        )
    blue_contribs = blue_agent_contrib.get(final_blue, {})
    blue_agent, blue_score = ("na", 0.0)
    if blue_contribs:
        blue_agent, blue_score = max(blue_contribs.items(), key=lambda x: x[1])
    explain = (
        f"来源Agent={','.join(source_agents or valid_agents)};"
        f"红球贡献={','.join(red_contrib_parts)};"
        f"蓝球贡献={final_blue:02d}:{blue_agent}({blue_score:.3f});"
        f"多样性替换={','.join(diversity_replacements) if diversity_replacements else '无'}"
    )
    explain_json = {
        "sources": source_agents or valid_agents,
        "red": red_contrib_json,
        "blue": {
            "ball": int(final_blue),
            "top_agent": blue_agent,
            "top_contribution": round(float(blue_score), 6),
            "agent_contributions": {
                a: round(float(s), 6) for a, s in sorted(blue_contribs.items(), key=lambda x: x[1], reverse=True)
            },
        },
        "diversity_replacements": diversity_replacements,
    }
    return {
        "red": final_red,
        "blue": final_blue,
        "sources": source_agents or valid_agents,
        "valid_agents": sorted(valid_agents),
        "explain": explain,
        "explain_json": explain_json,
        "diversity_replacements": diversity_replacements,
    }


def build_lead_agent_report(
    lead_model: Dict[str, Dict[str, float]],
    gap_result: Dict[str, object],
    expert_teams: Dict[str, Dict[str, object]],
) -> Dict[str, object]:
    ordered_weights = sorted(
        lead_model["weights"].items(), key=lambda item: item[1], reverse=True
    )
    top_agent, top_weight = ordered_weights[0]
    second_weight = ordered_weights[1][1] if len(ordered_weights) > 1 else 0.0
    confidence = max(0.0, top_weight - second_weight)
    healthy = [name for name, payload in expert_teams.items() if not payload.get("error")]
    failed = [name for name, payload in expert_teams.items() if payload.get("error")]
    top3 = []
    for agent, weight in ordered_weights[:3]:
        top3.append(
            {
                "agent": agent,
                "weight": round(weight, 3),
                "diff": round(lead_model["diff_scores"][agent], 3),
            }
        )
    mode = "保守" if confidence < 0.06 else "进取"
    if float(gap_result.get("factor", 1.0)) < 1.0:
        mode = "纠偏"
    report_lines = [
        f"策略风格={mode}",
        f"领跑Agent={top_agent}",
        f"权重稳定度={confidence:.3f}",
        f"团队健康={len(healthy)}/{len(expert_teams)}",
    ]
    return {
        "mode": mode,
        "top_agent": top_agent,
        "stability": confidence,
        "healthy_agents": healthy,
        "failed_agents": failed,
        "top3": top3,
        "archive_summary": ";".join(report_lines),
    }


def next_draw_date_str(records: List[Dict]) -> str:
    """计算下一期开奖日期（双色球每周二四日开奖）"""
    DRAW_WEEKDAYS = {1, 3, 6}  # Tuesday=1, Thursday=3, Sunday=6
    if records:
        latest_date_str = str(records[0].get("date", "")).strip()
        try:
            latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            latest_date = datetime.now().date()
    else:
        latest_date = datetime.now().date()
    next_date = latest_date + timedelta(days=1)
    while next_date.weekday() not in DRAW_WEEKDAYS:
        next_date += timedelta(days=1)
    weekdays_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{next_date.strftime('%m月%d日')} {weekdays_cn[next_date.weekday()]}"

def next_target_period(records: List[Dict]) -> str:
    if not records:
        return datetime.now().strftime("%Y%m%d")
    latest = str(records[0].get("period", "")).strip()
    if latest.isdigit():
        return str(int(latest) + 1)
    return f"{latest}_next"


def latest_completed_draw_date(now: Optional[datetime] = None):
    current = now or datetime.now()
    cutoff_passed = (
        current.hour > DRAW_CUTOFF_HOUR
        or (current.hour == DRAW_CUTOFF_HOUR and current.minute >= DRAW_CUTOFF_MINUTE)
    )
    candidate = current.date() if current.weekday() in DRAW_WEEKDAYS and cutoff_passed else current.date() - timedelta(days=1)
    while candidate.weekday() not in DRAW_WEEKDAYS:
        candidate -= timedelta(days=1)
    return candidate


def is_data_stale(latest_record_date: str, now: Optional[datetime] = None):
    expected_date = latest_completed_draw_date(now=now)
    try:
        latest_date = datetime.strptime(str(latest_record_date), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return True, {
            "latest_record_date": str(latest_record_date),
            "expected_latest_draw_date": expected_date.isoformat(),
            "checked_at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
            "error": "invalid_latest_record_date",
        }
    stale = latest_date < expected_date
    return stale, {
        "latest_record_date": latest_date.isoformat(),
        "expected_latest_draw_date": expected_date.isoformat(),
        "checked_at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description='双色球预测工具')
    parser.add_argument('--mode', '-m', default='team', choices=['single', 'team', 'team-cover'],
                       help='预测模式：single=单策略，team=多Agent团队，team-cover=覆盖优化实验模式')
    parser.add_argument('--strategy', '-s', default='balanced',
                       choices=['hot', 'cold', 'missing', 'balanced', 'random', 'cycle', 'sum', 'zone'],
                       help='预测策略（新增：cycle=周期性, sum=和值趋势, zone=区间平衡）')
    parser.add_argument('--num', '-n', type=int, default=5,
                       help='生成注数（team 模式固定输出 5 注）')
    parser.add_argument('--all', '-a', action='store_true',
                       help='使用所有策略')
    parser.add_argument('--learn-cycles', type=int, default=24,
                       help='主Agent差异学习回看期数（仅team模式生效）')
    parser.add_argument('--seed', type=int, default=None,
                       help='随机种子（用于复现实验）')
    parser.add_argument('--weight-patch', default=None,
                       help='权重补丁文件路径（来自 analyze_archive 导出的 weight_patch.json）')
    parser.add_argument('--team-backtest', action='store_true',
                       help='运行 team 端到端矩阵回测（只读历史数据，不写归档）')
    parser.add_argument('--team-cover-backtest', action='store_true',
                       help='运行 team-cover 实验模式回测（只读历史数据，不写归档）')
    parser.add_argument('--team-stability-backtest', action='store_true',
                       help='运行 dynamic-vs-legacy 多窗口多种子稳定性回测（只读，不写归档）')
    parser.add_argument('--stability-windows', default='36,72,108,144',
                       help='稳定性回测窗口，逗号分隔（默认36,72,108,144）')
    parser.add_argument('--stability-seeds', default='7,42,101,202,777,2026',
                       help='稳定性回测随机种子，逗号分隔')
    parser.add_argument('--stability-export-prefix', default=None,
                       help='稳定性报告导出前缀；写入 JSON、runs.csv 和 summary.csv')
    parser.add_argument('--team-threshold-calibration', action='store_true',
                       help='运行动态偏移阈值的扩展窗口校准（只读，不写归档）')
    parser.add_argument('--calibration-train-cycles', type=int, default=36,
                       help='每个校准折用于选择阈值的训练回测期数（默认36）')
    parser.add_argument('--calibration-validation-cycles', type=int, default=12,
                       help='每个校准折的后续未见验证期数（默认12）')
    parser.add_argument('--calibration-folds', type=int, default=3,
                       help='扩展窗口校准折数（默认3）')
    parser.add_argument('--calibration-seeds', default='42',
                       help='校准随机种子，逗号分隔（默认42）')
    parser.add_argument('--calibration-one-thresholds', default='0.38,0.42,0.46',
                       help='单偏移分数阈值候选，逗号分隔')
    parser.add_argument('--calibration-two-thresholds', default='0.54,0.58,0.62',
                       help='双偏移分数阈值候选，逗号分隔')
    parser.add_argument('--calibration-gap-thresholds', default='0.02,0.04,0.06',
                       help='最小分数差候选，逗号分隔')
    parser.add_argument('--calibration-grid-mode', choices=['one_factor', 'cartesian'], default='one_factor',
                       help='阈值网格：one_factor=单因素邻域（默认），cartesian=全组合')
    parser.add_argument('--calibration-export-prefix', default=None,
                       help='校准报告导出前缀；写入 JSON、runs.csv 和 summary.csv')
    parser.add_argument('--backtest-cycles', type=int, default=36,
                       help='team 端到端矩阵回测期数（默认36期）')
    parser.add_argument('--backtest-use-current-patches', action='store_true',
                       help='离线实验：回测时显式加载当前补丁（默认关闭，避免未来信息泄漏）')
    parser.add_argument('--advanced', '-adv', action='store_true',
                       help='使用高级综合分析（时间加权+关联分析+模式识别+遗传算法）')
    parser.add_argument('--enhanced', '-e', action='store_true',
                       help='启用增强分析（融合奖池/销售额/可视化模式权重）')
    
    args = parser.parse_args()
    rng = random.Random(args.seed)
    
    print("=" * 60)
    print("🎱 双色球预测结果")
    print("=" * 60)

    # 加载数据
    try:
        data = load_data()
        records = data['records']
        print(f"\n📊 基于 {len(records)} 期历史数据")
        print(f"📅 数据范围: {records[-1]['date']} 至 {records[0]['date']}")
        print(f"🕐 数据更新时间: {data['metadata']['last_updated']}")
    except Exception as e:
        print(f"❌ 加载数据失败: {e}")
        print("💡 请先运行: python update_data.py")
        return

    stale, stale_detail = is_data_stale(records[0]['date'])
    if stale:
        # 回测模式只读历史数据，允许在数据过期时继续运行
        if not args.team_backtest and not args.team_cover_backtest and not args.team_stability_backtest and not args.team_threshold_calibration:
            print("\n⚠️ 本地开奖数据已落后于最近应开奖期，已停止本次预测。")
            print(f"📌 本地最新开奖日: {stale_detail['latest_record_date']}")
            print(f"📌 应有最新开奖日: {stale_detail['expected_latest_draw_date']}")
            if stale_detail.get("error"):
                print("📌 数据日期字段异常，无法确认是否已更新。")
            print("💡 请先运行: python update_data.py")
            return
        print("\n⚠️ 本地开奖数据已落后，回测模式仅使用现有历史数据。")
    
    # 分析数据
    analysis = analyze_hot_cold(records)
    print(f"\n🔥 热号TOP10: {' '.join([f'{n:02d}' for n in analysis['hot_red']])}")
    print(f"❄️ 冷号BOTTOM10: {' '.join([f'{n:02d}' for n in analysis['cold_red']])}")
    
    # 生成预测
    print("\n" + "=" * 60)
    print("🎯 预测号码")
    print("=" * 60)

    if args.team_threshold_calibration:
        runtime_config, initial_weights, patch_source = resolve_backtest_priors(
            args.backtest_use_current_patches, args.weight_patch
        )
        try:
            calibration_seeds = [int(value.strip()) for value in str(args.calibration_seeds).split(",") if value.strip()]
            one_thresholds = [float(value.strip()) for value in str(args.calibration_one_thresholds).split(",") if value.strip()]
            two_thresholds = [float(value.strip()) for value in str(args.calibration_two_thresholds).split(",") if value.strip()]
            gap_thresholds = [float(value.strip()) for value in str(args.calibration_gap_thresholds).split(",") if value.strip()]
        except ValueError:
            parser.error("校准 seeds 必须是整数，阈值候选必须是逗号分隔的数字")
        if not calibration_seeds or not one_thresholds or not two_thresholds or not gap_thresholds:
            parser.error("校准至少需要一个 seed 和每类至少一个阈值候选")
        if args.calibration_train_cycles <= 0 or args.calibration_validation_cycles <= 0 or args.calibration_folds <= 0:
            parser.error("校准训练期数、验证期数和折数必须大于0")
        print(f"\n🧪 动态阈值滚动校准先验: {patch_source}（默认 clean）")

        def _print_calibration_progress(update: Dict[str, object]) -> None:
            print(
                f"\r⏳ calibration: {int(update.get('current', 0))}/{int(update.get('total', 0))} "
                f"| fold={update.get('fold')} | phase={update.get('phase')}",
                end="", flush=True,
            )

        try:
            report = team_threshold_calibration_report(
                records,
                train_cycles=args.calibration_train_cycles,
                validation_cycles=args.calibration_validation_cycles,
                fold_count=args.calibration_folds,
                seeds=calibration_seeds,
                runtime_config=runtime_config,
                initial_weights=initial_weights,
                one_thresholds=one_thresholds,
                two_thresholds=two_thresholds,
                gap_thresholds=gap_thresholds,
                grid_mode=args.calibration_grid_mode,
                progress_callback=_print_calibration_progress,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print("\n\n📊 动态偏移阈值滚动校准:")
        if not report["folds"]:
            print("  - 数据不足，无法构造训练/验证折。")
        for fold in report["folds"]:
            thresholds = fold["selected_thresholds"]
            print(
                f"  - fold={fold['fold']} train<= {fold['train_end_period']} "
                f"validate={fold['validation_start_period']}..{fold['validation_end_period']} | "
                f"one={thresholds['one_score_threshold']:.3f} "
                f"two={thresholds['two_score_threshold']:.3f} gap={thresholds['min_score_gap']:.3f} | "
                f"vs-default={fold['selected_vs_default_delta']:+.4f} "
                f"vs-legacy={fold['selected_vs_legacy_delta']:+.4f}"
            )
        aggregate = report["aggregate"]
        print(
            f"  - 验证集相对默认动态均值 "
            f"{float(aggregate['selected_vs_default_delta']['mean']):+.4f} "
            f"95%CI [{float(aggregate['selected_vs_default_delta']['ci95_low']):+.4f}, "
            f"{float(aggregate['selected_vs_default_delta']['ci95_high']):+.4f}]"
        )
        if args.calibration_export_prefix:
            paths = export_backtest_report(report, args.calibration_export_prefix)
            print(f"  - JSON: {paths['json']}")
            print(f"  - runs CSV: {paths['runs_csv']}")
            print(f"  - summary CSV: {paths['summary_csv']}")
        print("  - 说明: 每折只用更早数据选择阈值，再在紧随其后的未见区间验证。")
        print("\n" + "=" * 60)
        print("⚠️ 仅供娱乐，不构成投注建议！")
        print("=" * 60)
        return

    if args.team_stability_backtest:
        runtime_config, initial_weights, patch_source = resolve_backtest_priors(
            args.backtest_use_current_patches, args.weight_patch
        )
        try:
            windows = [int(value.strip()) for value in str(args.stability_windows).split(",") if value.strip()]
            seeds = [int(value.strip()) for value in str(args.stability_seeds).split(",") if value.strip()]
        except ValueError:
            parser.error("--stability-windows 和 --stability-seeds 必须是逗号分隔的整数")
        if not windows or not seeds:
            parser.error("稳定性回测至少需要一个窗口和一个 seed")
        print(f"\n🧪 稳定性回测先验: {patch_source}（默认 clean）")

        def _print_stability_progress(update: Dict[str, object]) -> None:
            print(
                f"\r⏳ stability 回测: {int(update.get('current', 0))}/{int(update.get('total', 0))} "
                f"| window={update.get('window')} | seed={update.get('seed')}",
                end="", flush=True,
            )

        report = team_stability_backtest_report(
            records, windows=windows, seeds=seeds, runtime_config=runtime_config,
            initial_weights=initial_weights, progress_callback=_print_stability_progress,
        )
        print("\n\n📊 dynamic vs legacy 配对结果:")
        for run in report["runs"]:
            print(
                f"  - window={run['window']} seed={run['seed']} | "
                f"dynamic={run['dynamic_objective']:.4f} legacy={run['legacy_objective']:.4f} "
                f"delta={run['objective_delta']:+.4f}"
            )
        aggregate = report["aggregate"]
        print(
            f"  - dynamic 稳健分 {aggregate['dynamic']['robust_score']:.4f} | "
            f"legacy 稳健分 {aggregate['legacy']['robust_score']:.4f} | "
            f"dynamic 正向 run 比例 {aggregate['paired']['dynamic_positive_ratio']:.2%}"
        )
        print(
            f"  - 配对目标差均值 {aggregate['paired']['objective_delta']['mean']:+.4f} | "
            f"标准差 {aggregate['paired']['objective_delta']['std']:.4f} | "
            f"最差 {aggregate['paired']['objective_delta']['min']:+.4f} | "
            f"最好 {aggregate['paired']['objective_delta']['max']:+.4f}"
        )
        paired_stats = aggregate["paired"]["objective_delta"]
        print(
            f"  - 中位数 {float(paired_stats.get('median', 0.0)):+.4f} | "
            f"四分位 [{float(paired_stats.get('q25', 0.0)):+.4f}, {float(paired_stats.get('q75', 0.0)):+.4f}] | "
            f"95%CI [{float(paired_stats.get('ci95_low', 0.0)):+.4f}, {float(paired_stats.get('ci95_high', 0.0)):+.4f}]"
        )
        if args.stability_export_prefix:
            paths = export_backtest_report(report, args.stability_export_prefix)
            print(f"  - JSON: {paths['json']}")
            print(f"  - runs CSV: {paths['runs_csv']}")
            print(f"  - summary CSV: {paths['summary_csv']}")
        print("  - 说明: 综合目标仅用于固定规则的离线比较；不代表中奖概率，也不进行事后调参。")
        print("\n" + "=" * 60)
        print("⚠️ 仅供娱乐，不构成投注建议！")
        print("=" * 60)
        return

    if args.team_cover_backtest:
        runtime_config, initial_weights, patch_source = resolve_backtest_priors(
            args.backtest_use_current_patches,
            args.weight_patch,
        )
        print(f"\n🧪 回测先验: {patch_source}（默认 clean；当前补丁需显式启用）")
        progress_state = {"last_len": 0}

        def _print_team_cover_backtest_progress(update: Dict[str, object]) -> None:
            current = int(update.get("current", 0))
            total = int(update.get("total", 0))
            period = str(update.get("period", ""))
            progress_text = f"\r⏳ team-cover 回测进度: {current}/{total} | period={period}"
            print(progress_text, end="", flush=True)
            progress_state["last_len"] = len(progress_text)

        report = team_cover_backtest_report(
            records,
            cycles=args.backtest_cycles,
            seed=args.seed,
            runtime_config=runtime_config,
            initial_weights=initial_weights,
            progress_callback=_print_team_cover_backtest_progress,
        )
        if progress_state["last_len"]:
            print()
        print("\n🧪 team-cover 对照回测:")
        section_names = {
            "team_cover": "实验模式",
            "team": "主链路 team",
            "conditional_random": "条件随机基准",
        }
        for key in ["team_cover", "team", "conditional_random"]:
            section = report.get(key, {})
            print(
                f"  - {section_names[key]}: 样本 {section.get('samples', 0)} | "
                f"单注平均分 {float(section.get('avg_ticket_score', 0.0)):.3f} | "
                f"best-of-5 平均分 {float(section.get('best_of_5_avg_score', 0.0)):.3f}"
            )
            print(
                f"    红2+率 {float(section.get('best_of_5_hit_rate_ge2', 0.0)):.2%} | "
                f"红3+率 {float(section.get('best_of_5_hit_rate_ge3', 0.0)):.2%} | "
                f"4红+1蓝 {int(section.get('best_of_5_hit_count_4plus1', 0))} 次/"
                f"{float(section.get('best_of_5_hit_rate_4plus1', 0.0)):.2%} | "
                f"蓝球池命中率 {float(section.get('blue_pool_hit_rate', 0.0)):.2%} | "
                f"最终蓝球命中率 {float(section.get('final_blue_hit_rate', 0.0)):.2%} | "
                f"平均重叠度 {float(section.get('avg_overlap', 0.0)):.3f}"
            )

        comparison = report.get("comparison", {})
        for key, title in [
            ("team_cover_vs_random_uplift", "实验模式 vs 条件随机 uplift"),
            ("team_vs_random_uplift", "主链路 team vs 条件随机 uplift"),
        ]:
            uplift = comparison.get(key, {})
            print(
                f"  - {title}: 单注平均分 {float(uplift.get('avg_ticket_score', 0.0)):+.3f} | "
                f"best-of-5 平均分 {float(uplift.get('best_of_5_avg_score', 0.0)):+.3f} | "
                f"红2+率 {float(uplift.get('best_of_5_hit_rate_ge2', 0.0)):+.2%} | "
                f"红3+率 {float(uplift.get('best_of_5_hit_rate_ge3', 0.0)):+.2%} | "
                f"4红+1蓝率 {float(uplift.get('best_of_5_hit_rate_4plus1', 0.0)):+.2%} | "
                f"蓝球池命中率 {float(uplift.get('blue_pool_hit_rate', 0.0)):+.2%} | "
                f"最终蓝球命中率 {float(uplift.get('final_blue_hit_rate', 0.0)):+.2%} | "
                f"平均重叠度改善 {float(uplift.get('avg_overlap', 0.0)):+.3f}"
            )
        print("  - 说明: team-cover 回测只读历史样本，不会写入 prediction_archive。")
        print("\n" + "=" * 60)
        print("⚠️ 仅供娱乐，不构成投注建议！")
        print("=" * 60)
        return

    if args.team_backtest:
        runtime_config, initial_weights, patch_source = resolve_backtest_priors(
            args.backtest_use_current_patches,
            args.weight_patch,
        )
        print(f"\n🧪 回测先验: {patch_source}（默认 clean；当前补丁需显式启用）")
        expert_backtest = backtest_report(records, learning_cycles=min(args.backtest_cycles, args.learn_cycles or args.backtest_cycles))
        progress_state = {"last_len": 0}

        def _print_team_backtest_progress(update: Dict[str, object]) -> None:
            current = int(update.get("current", 0))
            total = int(update.get("total", 0))
            period = str(update.get("period", ""))
            progress_text = f"\r⏳ team 回测进度: {current}/{total} | period={period}"
            print(progress_text, end="", flush=True)
            progress_state["last_len"] = len(progress_text)

        team_backtest = team_matrix_backtest_report(
            records,
            cycles=args.backtest_cycles,
            seed=args.seed,
            runtime_config=runtime_config,
            initial_weights=initial_weights,
            progress_callback=_print_team_backtest_progress,
        )
        if progress_state["last_len"]:
            print()
        print("\n📊 单专家回测:")
        print(
            f"  - 样本 {expert_backtest['overall']['samples']} | 平均分 {expert_backtest['overall']['avg_score']:.3f} | "
            f"红2+命中率 {expert_backtest['overall']['hit_rate_ge2']:.2%} | 蓝球命中率 {expert_backtest['overall']['blue_hit_rate']:.2%}"
        )
        print("\n🧪 最终链路回测:")
        print(
            f"  - 样本 {team_backtest['overall']['samples']} | 单注平均分 {team_backtest['overall']['avg_ticket_score']:.3f} | "
            f"best-of-5 平均分 {team_backtest['overall']['best_of_5_avg_score']:.3f}"
        )
        overall = team_backtest['overall']
        print(
            f"  - best-of-5 红2+率 {overall['best_of_5_hit_rate_ge2']:.2%} | "
            f"红3+率 {overall['best_of_5_hit_rate_ge3']:.2%} | "
            f"红4+率 {overall.get('best_of_5_hit_rate_ge4', 0):.2%}"
        )
        print(
            f"  - best-of-5 红5+率 {overall.get('best_of_5_hit_rate_ge5', 0):.2%} | "
            f"红6率 {overall.get('best_of_5_hit_rate_ge6', 0):.2%} | "
            f"蓝球池命中率 {overall['blue_pool_hit_rate']:.2%}"
        )
        print(
            f"  - 4红+1蓝（同一注）{int(overall.get('best_of_5_hit_count_4plus1', 0))} 次 / "
            f"{overall.get('best_of_5_hit_rate_4plus1', 0):.2%} | "
            f"至少4红+蓝 {int(overall.get('best_of_5_hit_count_ge4_plus_blue', 0))} 次 / "
            f"{overall.get('best_of_5_hit_rate_ge4_plus_blue', 0):.2%}"
        )
        print(
            f"  - 最终5注蓝球命中率 {overall['final_blue_hit_rate']:.2%} | "
            f"组合平均重叠度 {overall.get('avg_overlap', 0):.3f}"
        )
        counterfactual = team_backtest.get("counterfactual", {})
        print(
            f"  - 动态偏移次数 0/1/2={counterfactual.get('offset_counts', {}).get('0', 0)}/"
            f"{counterfactual.get('offset_counts', {}).get('1', 0)}/"
            f"{counterfactual.get('offset_counts', {}).get('2', 0)} | "
            f"偏移票分数增量 {float(counterfactual.get('avg_score_delta', 0.0)):+.3f} | "
            f"best-of-5 增量 {float(counterfactual.get('best_of_5_avg_score_delta', 0.0)):+.3f}"
        )
        calibration = team_backtest.get("blue_calibration", {})
        print(
            f"  - 蓝球排名校准 top1={float(calibration.get('top1_hit_rate', 0.0)):.2%} | "
            f"top3={float(calibration.get('top3_hit_rate', 0.0)):.2%} | "
            f"命中时平均排名={float(calibration.get('avg_hit_rank', 0.0)):.2f}"
        )
        if team_backtest["matrix_rows"]:
            print("  - 矩阵行表现:")
            for row in team_backtest["matrix_rows"]:
                print(f"    row={row['row_id']} | samples={row['samples']} | avg_score={row['avg_score']:.3f}")
        print("\n" + "=" * 60)
        print("⚠️ 仅供娱乐，不构成投注建议！")
        print("=" * 60)
        return

    if args.mode == 'team-cover':
        latest_archive = load_latest_archive()
        gap_result = evaluate_last_prediction_gap(latest_archive, records[0])
        resolved_patch_path, patch_source = resolve_weight_patch_path(args.weight_patch)
        param_patch_path = find_default_param_patch()
        matrix_patch_path = find_default_matrix_patch()
        runtime_config = resolve_runtime_config()
        initial_weights = load_weight_patch(resolved_patch_path)
        lead_model = train_lead_agent(
            records,
            learning_cycles=args.learn_cycles,
            initial_weights=initial_weights,
        )
        backtest = backtest_report(records, learning_cycles=args.learn_cycles)
        diff_factor = float(gap_result["factor"])
        print(f"\n🧪 team-cover 实验模式（回看 {args.learn_cycles} 期进行差异学习）")
        print(f"🧠 主Agent差异学习: {gap_result['summary']}")
        if resolved_patch_path:
            if initial_weights:
                print(f"🧩 已应用权重补丁: {resolved_patch_path}")
            else:
                print(f"⚠️ 权重补丁不可用，已忽略: {resolved_patch_path}")
        if param_patch_path:
            print(f"🧪 已应用参数补丁: {param_patch_path}")
        if matrix_patch_path:
            print(f"🧭 已应用矩阵补丁: {matrix_patch_path}")
        print(
            f"📊 单专家参考回测: 样本 {backtest['overall']['samples']} | 平均分 {backtest['overall']['avg_score']:.3f} | "
            f"红2+命中率 {backtest['overall']['hit_rate_ge2']:.2%} | 蓝球命中率 {backtest['overall']['blue_hit_rate']:.2%}"
        )

        team_ticket_count = resolve_team_ticket_count(args.num)
        if args.num != team_ticket_count:
            print(f"📐 team-cover 实验模式固定输出 {team_ticket_count} 注。")
        expert_teams = build_expert_teams(records, tickets=team_ticket_count, seed=args.seed)
        failed = [name for name, payload in expert_teams.items() if payload.get("error")]
        if failed:
            print(f"\n⚠️ 专家团队降级: {', '.join(failed)}")
        lead_report = build_lead_agent_report(lead_model, gap_result, expert_teams)

        print("\n覆盖优化实验结果:")
        target_period = next_target_period(records)
        next_date = next_draw_date_str(records)
        print(f"📅 预测期号: {target_period} | 预计开奖: {next_date}")
        cover_runtime = runtime_config.get("cover_mode", {}) if isinstance(runtime_config, dict) else {}
        print(
            f"📐 候选红球池: {int(cover_runtime.get('candidate_pool_size', CORE_RED_POOL_SIZE))}球 | "
            f"蓝球桶容量: {int(cover_runtime.get('blue_bucket_size', CORE_BLUE_POOL_SIZE))}球 | "
            f"固定输出: {team_ticket_count} 注"
        )
        snapshot = build_cover_candidate_snapshot(
            expert_teams,
            lead_model,
            diff_factor=diff_factor,
            records=records,
            runtime_config=runtime_config,
        )
        red_ranked = list(snapshot.get("red_ranked", []))
        if red_ranked:
            print(f"  🔴 候选红球池: {' '.join(f'{int(ball):02d}' for ball in red_ranked)}")
        blue_buckets = snapshot.get("blue_buckets", {}) if isinstance(snapshot, dict) else {}
        if isinstance(blue_buckets, dict):
            for bucket_name, title in [("main", "主攻"), ("explore", "探索"), ("reversion", "回补")]:
                bucket_values = [int(ball) for ball in blue_buckets.get(bucket_name, []) or []]
                if bucket_values:
                    print(f"  🔵 蓝球{title}桶: {' '.join(f'{ball:02d}' for ball in bucket_values)}")
        final_tickets = generate_team_cover_tickets(
            snapshot,
            runtime_config=runtime_config,
            seed=args.seed,
        )
        for i, final_ticket in enumerate(final_tickets):
            red, blue = final_ticket["red"], final_ticket["blue"]
            sources = final_ticket.get("sources", [])
            source_text = ",".join(sources) if sources else "cover"
            print(f"  第{i+1}注: 红球 {' '.join([f'{b:02d}' for b in red])} + 蓝球 {blue:02d} | 来源 {source_text}")
        summary = build_archive_lead_summary(
            diff_factor,
            lead_report,
            patch_source=patch_source,
            mode="team_cover",
        )
        archive_metadata = build_archive_metadata(
            runtime_config,
            prediction_seed=args.seed,
            patch_paths=(resolved_patch_path, param_patch_path, matrix_patch_path),
        )
        saved_path = save_compact_prediction(target_period, final_tickets, summary, metadata=archive_metadata)
        print(f"\n💾 已归档本期精简预测: {saved_path}")
    elif args.mode == 'team':
        latest_archive = load_latest_archive()
        gap_result = evaluate_last_prediction_gap(latest_archive, records[0])
        resolved_patch_path, patch_source = resolve_weight_patch_path(args.weight_patch)
        param_patch_path = find_default_param_patch()
        matrix_patch_path = find_default_matrix_patch()
        runtime_config = resolve_runtime_config()
        initial_weights = load_weight_patch(resolved_patch_path)
        lead_model = train_lead_agent(
            records,
            learning_cycles=args.learn_cycles,
            initial_weights=initial_weights,
        )
        backtest = backtest_report(records, learning_cycles=args.learn_cycles)
        diff_factor = float(gap_result["factor"])
        print(f"\n🤖 多Agent团队模式（回看 {args.learn_cycles} 期进行差异学习）")
        print(f"🧠 主Agent差异学习: {gap_result['summary']}")
        if resolved_patch_path:
            if initial_weights:
                print(f"🧩 已应用权重补丁: {resolved_patch_path}")
            else:
                print(f"⚠️ 权重补丁不可用，已忽略: {resolved_patch_path}")
        if param_patch_path:
            print(f"🧪 已应用参数补丁: {param_patch_path}")
        if matrix_patch_path:
            print(f"🧭 已应用矩阵补丁: {matrix_patch_path}")
        print("👑 主Agent学习权重:")
        for agent, weight in sorted(lead_model["weights"].items(), key=lambda x: x[1], reverse=True):
            diff = lead_model["diff_scores"][agent]
            print(f"  - {agent:8s} 权重 {weight:.3f} | 差异均值 {diff:+.3f}")

        team_ticket_count = resolve_team_ticket_count(args.num)
        if args.num != team_ticket_count:
            print(f"📐 旋转矩阵出票已启用，team 模式固定输出 {team_ticket_count} 注。")
        expert_teams = build_expert_teams(records, tickets=team_ticket_count, seed=args.seed)
        failed = [name for name, payload in expert_teams.items() if payload.get("error")]
        if failed:
            print(f"\n⚠️ 专家团队降级: {', '.join(failed)}")
        lead_report = build_lead_agent_report(lead_model, gap_result, expert_teams)
        top3_text = " | ".join(
            [f"{row['agent']}:{row['weight']:.3f}/{row['diff']:+.3f}" for row in lead_report["top3"]]
        )
        print("\n📘 主Agent学习报告:")
        print(f"  - 策略风格: {lead_report['mode']}")
        print(f"  - 领跑Agent: {lead_report['top_agent']}")
        print(f"  - 权重稳定度: {lead_report['stability']:.3f}")
        print(f"  - 团队健康度: {len(lead_report['healthy_agents'])}/{len(AGENT_TEAMS)}")
        print(f"  - TOP3画像: {top3_text}")
        print(
            f"  - 回测总览: 样本 {backtest['overall']['samples']} | 平均分 {backtest['overall']['avg_score']:.3f} | "
            f"红2+命中率 {backtest['overall']['hit_rate_ge2']:.2%} | 蓝球命中率 {backtest['overall']['blue_hit_rate']:.2%}"
        )

        print("\n团队融合结果:")
        target_period = next_target_period(records)
        next_date = next_draw_date_str(records)
        print(f"📅 预测期号: {target_period} | 预计开奖: {next_date}")
        print(f"📐 红球核心池: {CORE_RED_POOL_SIZE}球 | 蓝球核心池: {CORE_BLUE_POOL_SIZE}球 | 旋转矩阵: {ROTATION_MATRIX_TYPE}")
        final_tickets = generate_final_team_tickets(
            expert_teams,
            lead_model=lead_model,
            diff_factor=diff_factor,
            records=records,
            runtime_config=runtime_config,
            seed=args.seed,
        )
        # Show pooled diagnostic info
        if records and len(records) >= 20:
            blue_engine = BlueBallEngine(records, config=_runtime_blue_params(runtime_config))
            blue_diag = blue_engine.predict(pool_size=6)
            cold_chase_str = ", ".join(f"{n:02d}(缺{m}期)" for n, m in blue_diag.get('cold_chase', []))
            if cold_chase_str:
                print(f"  🔵 蓝球追冷目标: {cold_chase_str}")
            engine_pool_str = " ".join(f"{n:02d}" for n in blue_diag['pool'])
            print(f"  🔵 蓝球引擎候选池: {engine_pool_str}")
        for i, final_ticket in enumerate(final_tickets):
            red, blue = final_ticket["red"], final_ticket["blue"]
            sources = final_ticket["sources"]
            explain = final_ticket.get("explain", "")
            explain_json = final_ticket.get("explain_json")
            source_text = ",".join(sources) if sources else "fallback"
            print(f"  第{i+1}注: 红球 {' '.join([f'{b:02d}' for b in red])} + 蓝球 {blue:02d} | 来源 {source_text}")
        summary = build_archive_lead_summary(diff_factor, lead_report, patch_source=patch_source)
        archive_metadata = build_archive_metadata(
            runtime_config,
            prediction_seed=args.seed,
            patch_paths=(resolved_patch_path, param_patch_path, matrix_patch_path),
        )
        saved_path = save_compact_prediction(target_period, final_tickets, summary, metadata=archive_metadata)
        print(f"\n💾 已归档本期精简预测: {saved_path}")
    else:
        strategies = ['hot', 'cold', 'missing', 'balanced', 'random', 'cycle', 'sum', 'zone'] if args.all else [args.strategy]
        strategy_names = {
            'hot': '追热策略',
            'cold': '追冷策略',
            'missing': '高遗漏策略',
            'balanced': '平衡策略',
            'random': '完全随机',
            'cycle': '周期性策略',
            'sum': '和值趋势策略',
            'zone': '区间平衡策略'
        }

        if args.advanced:
            # 使用高级综合分析
            print("\n🚀 使用高级综合分析模式...")
            for i in range(args.num):
                red, blue = generate_advanced_prediction(records, rng=rng)
                print(f"  第{i+1}注: 红球 {' '.join([f'{b:02d}' for b in red])} + 蓝球 {blue:02d}")
        else:
            for strategy in strategies:
                name = strategy_names.get(strategy, strategy)
                print(f"\n{name}:")

                for i in range(args.num):
                    red, blue = generate_prediction(records, strategy, rng=rng, use_enhanced=args.enhanced)
                    print(f"  第{i+1}注: 红球 {' '.join([f'{b:02d}' for b in red])} + 蓝球 {blue:02d}")
    
    print("\n" + "=" * 60)
    print("⚠️ 仅供娱乐，不构成投注建议！")
    print("=" * 60)


# ============================================================================
# 高级分析模块 - 综合方案
# ============================================================================

class AdvancedAnalyzer:
    """高级分析器：整合时间加权、关联分析、模式识别和遗传算法"""
    
    def __init__(self, records: List[Dict]):
        self.records = records
        self.red_range = range(1, 34)
        self.blue_range = range(1, 17)
    
    # ========================================================================
    # 1. 时间加权分析（指数衰减）
    # ========================================================================
    def analyze_time_weighted(self, decay_factor: float = 0.95) -> Dict:
        """时间加权分析：近期数据权重更高，远期数据指数衰减"""
        red_weights = Counter()
        blue_weights = Counter()
        
        for idx, record in enumerate(self.records):
            # 权重指数衰减：越新的数据权重越高
            weight = decay_factor ** idx
            for ball in record['red_balls']:
                red_weights[ball] += weight
            blue_weights[record['blue_ball']] += weight
        
        # 归一化权重
        max_red = max(red_weights.values()) if red_weights else 1
        max_blue = max(blue_weights.values()) if blue_weights else 1
        
        red_scores = {n: red_weights.get(n, 0) / max_red for n in self.red_range}
        blue_scores = {n: blue_weights.get(n, 0) / max_blue for n in self.blue_range}
        
        return {
            'red_scores': red_scores,
            'blue_scores': blue_scores,
            'top_red': sorted(red_scores.items(), key=lambda x: x[1], reverse=True),
            'top_blue': sorted(blue_scores.items(), key=lambda x: x[1], reverse=True)
        }
    
    # ========================================================================
    # 2. AC值分析（算术复杂度）
    # ========================================================================
    def calculate_ac_value(self, balls: List[int]) -> int:
        """计算一组红球的AC值（算术复杂度）
        
        AC值 = 两两差值的不同值数量 - 5
        反映号码的离散程度：
        - AC值小：差值重复多，号码有关联（连号、等差号）
        - AC值大：号码杂乱无章
        历史开奖AC值通常在 5-10 之间
        """
        if len(balls) < 2:
            return 0
        sorted_balls = sorted(balls)
        diffs = set()
        for i in range(len(sorted_balls)):
            for j in range(i + 1, len(sorted_balls)):
                diffs.add(sorted_balls[j] - sorted_balls[i])
        return len(diffs) - (len(sorted_balls) - 1)

    def analyze_ac_value_distribution(self, recent_periods: int = 50) -> Dict:
        """分析近期AC值分布，确定合理的AC值范围"""
        if len(self.records) < 5:
            return {'target_ac_range': (4, 10), 'avg_ac': 7.0, 'ac_std': 2.0}
        
        recent = self.records[:recent_periods]
        ac_values = [self.calculate_ac_value(r['red_balls']) for r in recent]
        
        avg_ac = sum(ac_values) / len(ac_values)
        variance = sum((x - avg_ac) ** 2 for x in ac_values) / len(ac_values)
        std_ac = math.sqrt(variance)
        
        # 目标范围：均值 ± 1个标准差
        target_min = max(3, int(avg_ac - std_ac))
        target_max = min(12, int(avg_ac + std_ac))
        
        return {
            'target_ac_range': (target_min, target_max),
            'avg_ac': avg_ac,
            'ac_std': std_ac,
            'ac_history': ac_values[:10]
        }

    # ========================================================================
    # 3. 熵值分析（信息熵）
    # ========================================================================
    def calculate_entropy(self, frequencies: Dict[int, int], total: int) -> float:
        """计算信息熵：衡量分布的不确定性
        
        熵值高：分布均匀，冷热不分明（每个号码出现概率接近）
        熵值低：分布集中，冷热分明（少数号码频繁出现）
        """
        if total <= 0:
            return 0.0
        entropy = 0.0
        for count in frequencies.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        return entropy

    def analyze_entropy_trend(self, window_sizes: List[int] = [20, 50, 100]) -> Dict:
        """分析不同时间窗口的熵值变化趋势
        
        返回：
        - 当前处于"冷热分明"还是"均匀分布"阶段
        - 熵值变化趋势（上升/下降）
        """
        if len(self.records) < max(window_sizes):
            return {'phase': 'unknown', 'entropy_scores': {}, 'trend': 'stable'}
        
        entropy_by_window = {}
        for window in window_sizes:
            recent = self.records[:window]
            red_freq = Counter()
            for r in recent:
                red_freq.update(r['red_balls'])
            total = sum(red_freq.values())
            entropy = self.calculate_entropy(red_freq, total)
            # 归一化到 [0, 1]：最大熵 = log2(33) ≈ 5.04
            max_entropy = math.log2(33)
            normalized = entropy / max_entropy
            entropy_by_window[window] = {
                'raw': entropy,
                'normalized': normalized
            }
        
        # 判断阶段：用最近20期的熵值
        recent_entropy = entropy_by_window[20]['normalized']
        if recent_entropy < 0.85:
            phase = 'polarized'  # 冷热分明
        elif recent_entropy > 0.95:
            phase = 'uniform'    # 均匀分布
        else:
            phase = 'balanced'   # 相对均衡
        
        # 趋势判断：比较近20期 vs 近50期
        trend = 'stable'
        if len(window_sizes) >= 2:
            e20 = entropy_by_window[window_sizes[0]]['normalized']
            e50 = entropy_by_window[window_sizes[1]]['normalized']
            if e20 > e50 + 0.05:
                trend = 'rising'    # 趋向均匀
            elif e20 < e50 - 0.05:
                trend = 'falling'   # 趋向集中
        
        return {
            'phase': phase,
            'entropy_scores': entropy_by_window,
            'trend': trend
        }

    # ========================================================================
    # 4. 号码关联分析（马尔可夫链 + 共现分析）
    # ========================================================================
    def analyze_number_correlation(self) -> Dict:
        """号码关联分析：分析哪些号码经常一起出现"""
        # 共现频率
        pair_counts = Counter()
        triple_counts = Counter()
        
        # 转移概率（马尔可夫链）
        red_transitions = defaultdict(Counter)
        
        for record in self.records:
            balls = sorted(record['red_balls'])
            
            # 分析两两共现
            for i in range(len(balls)):
                for j in range(i + 1, len(balls)):
                    pair_counts[(balls[i], balls[j])] += 1
                
                # 分析三连号共现
                for j in range(i + 1, len(balls)):
                    for k in range(j + 1, len(balls)):
                        triple_counts[(balls[i], balls[j], balls[k])] += 1
            
            # 马尔可夫转移（当前期到下一期的号码转移）
            # 简化版：记录相邻号码的关系
            for i in range(len(balls) - 1):
                red_transitions[balls[i]][balls[i + 1]] += 1
        
        # 找出最频繁的关联对
        top_pairs = pair_counts.most_common(20)
        top_triples = triple_counts.most_common(10)
        
        return {
            'pair_counts': dict(pair_counts),
            'triple_counts': dict(triple_counts),
            'top_pairs': top_pairs,
            'top_triples': top_triples,
            'transitions': dict(red_transitions)
        }
    
    # ========================================================================
    # 3. 模式识别策略
    # ========================================================================
    def analyze_patterns(self, recent_periods: int = 20) -> Dict:
        """模式识别：连号、同尾号、区间分布、奇偶比、大小比"""
        recent = self.records[:recent_periods]
        
        patterns = {
            'consecutive': [],  # 连号模式
            'same_tail': [],    # 同尾号模式
            'odd_even': [],     # 奇偶比
            'big_small': [],    # 大小比
            'zone_dist': [],    # 区间分布
            'sum_range': []     # 和值范围
        }
        
        for record in recent:
            balls = sorted(record['red_balls'])
            
            # 1. 连号检测
            consecutive_groups = []
            current_group = [balls[0]]
            for i in range(1, len(balls)):
                if balls[i] == balls[i-1] + 1:
                    current_group.append(balls[i])
                else:
                    if len(current_group) >= 2:
                        consecutive_groups.append(tuple(current_group))
                    current_group = [balls[i]]
            if len(current_group) >= 2:
                consecutive_groups.append(tuple(current_group))
            patterns['consecutive'].extend(consecutive_groups)
            
            # 2. 同尾号检测
            tails = defaultdict(list)
            for ball in balls:
                tails[ball % 10].append(ball)
            same_tail_groups = [v for v in tails.values() if len(v) >= 2]
            patterns['same_tail'].extend([tuple(g) for g in same_tail_groups])
            
            # 3. 奇偶比
            odd_count = sum(1 for b in balls if b % 2 == 1)
            patterns['odd_even'].append((odd_count, 6 - odd_count))
            
            # 4. 大小比（1-16小，17-33大）
            big_count = sum(1 for b in balls if b >= 17)
            patterns['big_small'].append((6 - big_count, big_count))
            
            # 5. 区间分布（1-11, 12-22, 23-33）
            zone1 = sum(1 for b in balls if 1 <= b <= 11)
            zone2 = sum(1 for b in balls if 12 <= b <= 22)
            zone3 = sum(1 for b in balls if 23 <= b <= 33)
            patterns['zone_dist'].append((zone1, zone2, zone3))
            
            # 6. 和值
            patterns['sum_range'].append(sum(balls))
        
        # 统计最频繁的模式
        from collections import Counter as PatternCounter
        
        return {
            'consecutive_freq': PatternCounter(patterns['consecutive']).most_common(5),
            'same_tail_freq': PatternCounter(patterns['same_tail']).most_common(5),
            'odd_even_freq': PatternCounter(patterns['odd_even']).most_common(3),
            'big_small_freq': PatternCounter(patterns['big_small']).most_common(3),
            'zone_dist_freq': PatternCounter(patterns['zone_dist']).most_common(3),
            'avg_sum': sum(patterns['sum_range']) / len(patterns['sum_range']) if patterns['sum_range'] else 100,
            'sum_std': self._calculate_std(patterns['sum_range']) if patterns['sum_range'] else 20
        }
    
    def _calculate_std(self, values: List[float]) -> float:
        """计算标准差"""
        if len(values) < 2:
            return 0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)
    
    # ========================================================================
    # 4. 遗传算法优化
    # ========================================================================
    class GeneticOptimizer:
        """遗传算法优化器"""
        
        def __init__(self, analyzer: 'AdvancedAnalyzer', population_size: int = 50, generations: int = 30, ac_range: Optional[Tuple[int, int]] = None):
            self.analyzer = analyzer
            self.population_size = population_size
            self.generations = generations
            self.records = analyzer.records
            self.ac_range = ac_range or (4, 10)  # 默认合理范围
            
            # 预计算历史数据用于适应度评估
            self.historical_sets = [set(r['red_balls']) for r in self.records[:50]]
            
            # 预计算AC值约束
            self.ac_min, self.ac_max = self.ac_range
        
        def create_individual(self, rng: random.Random) -> Set[int]:
            """创建一个个体（6个红球），确保AC值在合理范围内"""
            max_attempts = 100
            for _ in range(max_attempts):
                individual = set(rng.sample(range(1, 34), 6))
                ac = self.analyzer.calculate_ac_value(list(individual))
                if self.ac_min <= ac <= self.ac_max:
                    return individual
            # 如果多次尝试都失败，返回最后一个
            return individual
        
        def fitness(self, individual: Set[int]) -> float:
            """多目标适应度函数：历史重合度 + AC值约束 + 冷热平衡 + 区间均衡"""
            if not self.historical_sets:
                return 0.5
            
            # 1. 计算与历史开奖的平均重合度
            total_score = 0
            for historical in self.historical_sets:
                intersection = len(individual & historical)
                # 奖励 2-4 个重合（实际中奖范围）
                if 2 <= intersection <= 4:
                    total_score += intersection * 0.3
                else:
                    total_score += intersection * 0.1
            
            avg_score = total_score / len(self.historical_sets)
            
            # 2. AC值约束：偏离目标范围则惩罚
            ac = self.analyzer.calculate_ac_value(list(individual))
            ac_penalty = 0
            if ac < self.ac_min:
                ac_penalty = (self.ac_min - ac) * 0.15  # 过于规律，惩罚
            elif ac > self.ac_max:
                ac_penalty = (ac - self.ac_max) * 0.1   # 过于杂乱，惩罚
            
            # 3. 冷热平衡奖励
            hot_cold_bonus = self._hot_cold_balance_bonus(individual)
            
            # 4. 区间均衡奖励
            zone_bonus = self._zone_balance_bonus(individual)
            
            # 5. 奇偶均衡奖励
            odd_even_bonus = self._odd_even_balance_bonus(individual)
            
            return avg_score + hot_cold_bonus + zone_bonus + odd_even_bonus - ac_penalty
        
        def _zone_balance_bonus(self, individual: Set[int]) -> float:
            """区间分布均衡奖励：1-11, 12-22, 23-33 每个区间至少1个"""
            zones = [0, 0, 0]
            for ball in individual:
                if ball <= 11:
                    zones[0] += 1
                elif ball <= 22:
                    zones[1] += 1
                else:
                    zones[2] += 1
            
            # 理想分布：2-2-2 或 2-2-1 或 2-1-2 等
            if all(z >= 1 for z in zones):
                # 额外奖励更均匀的分布
                variance = sum((z - 2) ** 2 for z in zones) / 3
                return 0.25 - variance * 0.05
            return 0
        
        def _odd_even_balance_bonus(self, individual: Set[int]) -> float:
            """奇偶均衡奖励：3奇3偶最优"""
            odd_count = sum(1 for b in individual if b % 2 == 1)
            # 理想是3奇3偶，偏离则递减奖励
            deviation = abs(odd_count - 3)
            return max(0, 0.15 - deviation * 0.05)
        
        def _hot_cold_balance_bonus(self, individual: Set[int]) -> float:
            """热冷平衡奖励"""
            # 简单版：检查是否包含不同区间的号码
            zones = [0, 0, 0]  # 1-11, 12-22, 23-33
            for ball in individual:
                if ball <= 11:
                    zones[0] += 1
                elif ball <= 22:
                    zones[1] += 1
                else:
                    zones[2] += 1
            
            # 奖励均匀分布
            if all(z >= 1 for z in zones):
                return 0.2
            return 0
        
        def crossover(self, parent1: Set[int], parent2: Set[int], rng: random.Random) -> Set[int]:
            """交叉操作"""
            # 取两个父代的交集，然后随机补充
            intersection = parent1 & parent2
            remaining = list((parent1 | parent2) - intersection)
            
            child = set(intersection)
            needed = 6 - len(child)
            
            if needed > 0 and remaining:
                child.update(rng.sample(remaining, min(needed, len(remaining))))
            
            # 如果还不够，随机补充
            if len(child) < 6:
                all_numbers = set(range(1, 34)) - child
                child.update(rng.sample(list(all_numbers), 6 - len(child)))
            
            return child
        
        def mutate(self, individual: Set[int], mutation_rate: float, rng: random.Random) -> Set[int]:
            """变异操作"""
            individual = set(individual)
            if rng.random() < mutation_rate:
                # 随机替换一个号码
                to_remove = rng.choice(list(individual))
                to_add = rng.choice([n for n in range(1, 34) if n not in individual])
                individual.remove(to_remove)
                individual.add(to_add)
            return individual
        
        def optimize(self, rng: random.Random = None) -> List[int]:
            """运行遗传算法优化"""
            rng = rng or random.Random()
            
            # 初始化种群
            population = [self.create_individual(rng) for _ in range(self.population_size)]
            
            for generation in range(self.generations):
                # 评估适应度
                fitness_scores = [(ind, self.fitness(ind)) for ind in population]
                fitness_scores.sort(key=lambda x: x[1], reverse=True)
                
                # 选择精英
                elite_size = self.population_size // 4
                new_population = [ind for ind, _ in fitness_scores[:elite_size]]
                
                # 交叉和变异产生新一代
                while len(new_population) < self.population_size:
                    parent1 = rng.choice([ind for ind, _ in fitness_scores[:self.population_size//2]])
                    parent2 = rng.choice([ind for ind, _ in fitness_scores[:self.population_size//2]])
                    child = self.crossover(parent1, parent2, rng)
                    child = self.mutate(child, 0.1, rng)
                    new_population.append(child)
                
                population = new_population
            
            # 返回最佳个体
            best = max(population, key=self.fitness)
            return sorted(best)
    
    # ========================================================================
    # 综合分析：整合所有方法
    # ========================================================================
    def comprehensive_analysis(self) -> Dict:
        """运行所有分析方法并整合结果"""
        print("\n" + "=" * 60)
        print("🔬 高级综合分析")
        print("=" * 60)
        
        # 1. 时间加权分析
        print("\n📊 1. 时间加权分析（指数衰减）...")
        time_weighted = self.analyze_time_weighted(decay_factor=0.95)
        print(f"   时间加权热号: {[n for n, _ in time_weighted['top_red'][:10]]}")
        
        # 2. AC值分析
        print("\n📐 2. AC值分析（算术复杂度）...")
        ac_analysis = self.analyze_ac_value_distribution(50)
        print(f"   近期AC均值: {ac_analysis['avg_ac']:.2f} ± {ac_analysis['ac_std']:.2f}")
        print(f"   目标AC范围: {ac_analysis['target_ac_range']}")
        
        # 3. 熵值分析
        print("\n🌡️ 3. 熵值趋势分析...")
        entropy_analysis = self.analyze_entropy_trend([20, 50, 100])
        phase_desc = {
            'polarized': '冷热分明（追热/追冷更有效）',
            'uniform': '均匀分布（平衡策略更有效）',
            'balanced': '相对均衡',
            'unknown': '数据不足'
        }
        trend_desc = {
            'rising': '趋向均匀',
            'falling': '趋向集中',
            'stable': '保持稳定'
        }
        print(f"   当前阶段: {phase_desc.get(entropy_analysis['phase'], entropy_analysis['phase'])}")
        print(f"   趋势: {trend_desc.get(entropy_analysis['trend'], entropy_analysis['trend'])}")
        for window, scores in entropy_analysis['entropy_scores'].items():
            print(f"   近{window}期归一化熵值: {scores['normalized']:.4f}")
        
        # 4. 关联分析
        print("\n🔗 4. 号码关联分析...")
        correlation = self.analyze_number_correlation()
        if correlation['top_pairs']:
            print(f"   高频关联对: {correlation['top_pairs'][:5]}")
        
        # 5. 模式识别
        print("\n🎯 5. 模式识别分析...")
        patterns = self.analyze_patterns(recent_periods=20)
        print(f"   常见奇偶比: {patterns['odd_even_freq'][:3]}")
        print(f"   常见大小比: {patterns['big_small_freq'][:3]}")
        print(f"   平均和值: {patterns['avg_sum']:.1f} ± {patterns['sum_std']:.1f}")
        
        # 6. 遗传算法优化（传入AC值约束）
        print("\n🧬 6. 遗传算法优化...")
        ga = self.GeneticOptimizer(
            self, population_size=30, generations=20,
            ac_range=ac_analysis['target_ac_range']
        )
        ga_result = ga.optimize()
        print(f"   遗传算法推荐: {ga_result}")
        
        return {
            'time_weighted': time_weighted,
            'ac_analysis': ac_analysis,
            'entropy_analysis': entropy_analysis,
            'correlation': correlation,
            'patterns': patterns,
            'genetic_result': ga_result
        }


def generate_advanced_prediction(records: List[Dict], rng: random.Random = None) -> Tuple[List[int], int]:
    """使用高级分析生成预测"""
    rng = rng or random.Random()
    analyzer = AdvancedAnalyzer(records)
    
    # 运行综合分析
    analysis = analyzer.comprehensive_analysis()
    
    # 整合多种方法生成红球（根据熵值阶段动态调整策略）
    red_candidates = set()
    entropy_phase = analysis['entropy_analysis']['phase']
    
    # 根据熵值阶段选择不同策略
    if entropy_phase == 'polarized':
        # 冷热分明阶段：更依赖时间加权（追热/追冷）
        time_top = [n for n, _ in analysis['time_weighted']['top_red'][:12]]
        red_candidates.update(time_top[:6])
    elif entropy_phase == 'uniform':
        # 均匀分布阶段：更依赖遗传算法和关联分析
        red_candidates.update(analysis['genetic_result'][:4])
        if analysis['correlation']['top_pairs']:
            for (a, b), count in analysis['correlation']['top_pairs'][:3]:
                red_candidates.add(a)
                red_candidates.add(b)
        # 补充一些时间加权高分号
        time_top = [n for n, _ in analysis['time_weighted']['top_red'][:6]]
        red_candidates.update(time_top[:2])
    else:
        # 均衡阶段：平衡使用所有策略
        time_top = [n for n, _ in analysis['time_weighted']['top_red'][:8]]
        red_candidates.update(time_top[:4])
        red_candidates.update(analysis['genetic_result'][:2])
        if analysis['correlation']['top_pairs']:
            for (a, b), count in analysis['correlation']['top_pairs'][:2]:
                red_candidates.add(a)
                red_candidates.add(b)
    
    # 根据模式补充
    patterns = analysis['patterns']
    
    # 根据常见奇偶比调整
    if patterns['odd_even_freq']:
        common_odd_even = patterns['odd_even_freq'][0][0]
        target_odd = common_odd_even[0]
    else:
        target_odd = 3
    
    # 根据和值范围调整
    target_sum_min = int(patterns['avg_sum'] - patterns['sum_std'])
    target_sum_max = int(patterns['avg_sum'] + patterns['sum_std'])
    
    # 从候选池中选择6个号码，尽量满足约束
    red_balls = sorted(red_candidates)
    if len(red_balls) < 6:
        # 补充号码（根据熵值阶段选择补充策略）
        all_numbers = set(range(1, 34)) - set(red_balls)
        needed = 6 - len(red_balls)
        if entropy_phase == 'polarized':
            # 冷热分明：补充时间加权高分号
            red_scores = {n: s for n, s in analysis['time_weighted']['top_red']}
            candidates = sorted(all_numbers, key=lambda x: red_scores.get(x, 0), reverse=True)
            red_balls.extend(candidates[:needed])
        else:
            # 均匀/均衡：随机补充保持多样性
            red_balls.extend(rng.sample(list(all_numbers), needed))
        red_balls = sorted(red_balls[:6])
    elif len(red_balls) > 6:
        # 根据时间加权分数筛选
        red_scores = {n: s for n, s in analysis['time_weighted']['top_red']}
        red_balls = sorted(red_candidates, key=lambda x: red_scores.get(x, 0), reverse=True)[:6]
    
    # 蓝球：结合时间加权和遗传算法思想
    blue_scores = analysis['time_weighted']['blue_scores']
    # 加权随机选择
    blue_candidates = list(range(1, 17))
    blue_weights = [blue_scores.get(n, 0.5) + 0.1 for n in blue_candidates]
    total_weight = sum(blue_weights)
    blue_probs = [w / total_weight for w in blue_weights]
    
    # 根据概率选择
    r = rng.random()
    cumulative = 0
    blue_ball = 1
    for i, prob in enumerate(blue_probs):
        cumulative += prob
        if r <= cumulative:
            blue_ball = blue_candidates[i]
            break
    
    return red_balls, blue_ball


if __name__ == "__main__":
    main()
