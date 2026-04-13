#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预测脚本：支持单策略与多 Agent 团队协同预测。"""

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple, Set
import math

# 尝试导入LSTM预测器
try:
    from lstm_predictor import generate_lstm_prediction, LSTMPredictor, TF_AVAILABLE
except ImportError:
    TF_AVAILABLE = False
    LSTMPredictor = None
    generate_lstm_prediction = None


DATA_FILE = "lottery_data.json"
ARCHIVE_DIR = "prediction_archive"
AGENT_TEAMS = ("hot", "cold", "missing", "balanced", "random", "cycle", "sum", "zone", "lstm")


def load_data():
    """加载数据"""
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze_hot_cold(records, recent_periods=40):
    """冷热号分析 - 优化：增加蓝球冷号分析；扩大窗口至40期捕捉更长趋势"""
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
        'cold_red': [n for n, c in red_freq[-10:]],
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


# ============================================================================
# 新增：3个高级Agent分析函数
# ============================================================================

def analyze_cycle(records, max_period=50):
    """周期性分析：分析号码是否存在周期性规律"""
    if len(records) < 10:
        return {'cycle_scores': {}, 'top_cycle': []}
    
    cycle_scores = {}
    
    for number in range(1, 34):
        # 获取该号码出现的期数索引
        appearances = [i for i, r in enumerate(records) if number in r['red_balls']]
        
        if len(appearances) < 3:
            cycle_scores[number] = 0
            continue
        
        # 计算间隔
        intervals = [appearances[i] - appearances[i-1] for i in range(1, len(appearances))]
        
        if not intervals:
            cycle_scores[number] = 0
            continue
        
        # 计算间隔的方差（方差越小，周期性越强）
        avg_interval = sum(intervals) / len(intervals)
        variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals) if len(intervals) > 1 else 0
        
        # 周期性得分（间隔越稳定，得分越高）
        if avg_interval > 0:
            stability = 1 / (1 + variance / (avg_interval ** 2))
            
            # 预测下期出现的概率（基于周期）
            last_appearance = appearances[-1]
            expected_next = last_appearance + avg_interval
            current_idx = len(records)
            
            # 距离预期出现时间的接近程度
            distance = abs(current_idx - expected_next)
            proximity_score = max(0, 1 - distance / avg_interval) if avg_interval > 0 else 0
            
            cycle_scores[number] = stability * proximity_score
        else:
            cycle_scores[number] = 0
    
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
    """从候选集中稳定采样红球，不足时自动补齐。"""
    unique_candidates = sorted(set(candidates))
    if len(unique_candidates) < required:
        remaining = [i for i in range(1, 34) if i not in unique_candidates]
        unique_candidates.extend(rng.sample(remaining, required - len(unique_candidates)))
    return sorted(rng.sample(unique_candidates, required))


def generate_prediction(records, strategy='balanced', rng: random.Random = None):
    """按单策略生成预测号码 - 优化：增加蓝球遗漏分析和趋势权重，支持8种策略"""
    rng = rng or random.Random()
    if not records:
        return sorted(rng.sample(range(1, 34), 6)), rng.randint(1, 16)
    
    analysis = {
        'hot_cold': analyze_hot_cold(records),
        'missing': analyze_missing(records),
        'blue_missing': analyze_blue_missing(records),
        'trend': analyze_trend(records)
    }
    
    hot_red = analysis['hot_cold']['hot_red']
    cold_red = analysis['hot_cold']['cold_red']
    high_missing = analysis['missing']['high_missing_red']
    hot_blue = analysis['hot_cold']['hot_blue']
    cold_blue = analysis['hot_cold']['cold_blue']
    high_missing_blue = analysis['blue_missing']['high_missing_blue']
    
    if strategy == 'hot':
        candidates = hot_red
        # 蓝球选择：热号为主，兼顾遗漏
        blue_candidates = hot_blue + high_missing_blue[:2]
    elif strategy == 'cold':
        candidates = cold_red
        # 蓝球选择：冷号 + 高遗漏
        blue_candidates = cold_blue + high_missing_blue[:3]
    elif strategy == 'missing':
        candidates = high_missing
        # 蓝球选择：高遗漏优先
        blue_candidates = high_missing_blue + cold_blue[:2]
    elif strategy == 'balanced':
        # 平衡策略优化：增加权重分配
        candidates = list(set(hot_red[:4] + cold_red[:4] + high_missing[:4]))
        # 蓝球平衡选择
        blue_candidates = list(set(hot_blue[:3] + high_missing_blue[:3]))
    elif strategy == 'cycle':
        # 周期性策略
        cycle_analysis = analyze_cycle(records)
        candidates = cycle_analysis['top_cycle'][:10]
        blue_candidates = list(range(1, 17))
    elif strategy == 'sum':
        # 和值趋势策略
        sum_analysis = analyze_sum_trend(records)
        # 根据和值权重选择号码
        weighted_candidates = sorted(
            sum_analysis['sum_weights'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        candidates = [n for n, w in weighted_candidates[:12]]
        blue_candidates = list(range(1, 17))
    elif strategy == 'zone':
        # 区间平衡策略
        zone_analysis = analyze_zone_balance(records)
        # 从各区热号中选择，优先选择需要补充的区
        candidates = []
        for zone in [1, 2, 3]:
            zone_hot = zone_analysis['zone_hot'][zone]
            # 根据该区需要的数量选择
            need = zone_analysis['target_zones'][zone]
            candidates.extend(zone_hot[:need + 1])
        candidates = list(set(candidates))
        blue_candidates = list(range(1, 17))
    elif strategy == 'lstm':
        # LSTM神经网络策略
        if TF_AVAILABLE and generate_lstm_prediction:
            try:
                return generate_lstm_prediction(records, sequence_length=10)
            except Exception as e:
                print(f"⚠️ LSTM预测失败: {e}，使用随机策略")
                return sorted(rng.sample(range(1, 34), 6)), rng.randint(1, 16)
        else:
            # TensorFlow未安装，使用随机策略
            return sorted(rng.sample(range(1, 34), 6)), rng.randint(1, 16)
    else:  # random
        return sorted(rng.sample(range(1, 34), 6)), rng.randint(1, 16)

    red_balls = _safe_red_sample(rng, candidates, required=6)
    
    # 蓝球选择优化：如果有候选池，加权随机选择；否则纯随机
    if blue_candidates:
        blue_ball = rng.choice(blue_candidates)
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


def build_archive_lead_summary(diff_factor: float, lead_report: Dict[str, object], patch_source: str) -> str:
    healthy_agents = lead_report.get("healthy_agents", []) or []
    archive_summary = lead_report.get("archive_summary", "")
    return f"factor={diff_factor:.2f};mode=team;patch_source={patch_source};agents={','.join(healthy_agents)};report={archive_summary}"


def _window_agent_performance(
    records: List[Dict],
    cycles: int,
    decay_gamma: float,
) -> Dict[str, object]:
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
        per_round_scores = {}
        for agent in AGENT_TEAMS:
            red, blue = generate_prediction(history, strategy=agent, rng=random.Random())
            per_round_scores[agent] = _ticket_score(red, blue, target)

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

    return {
        "cycles": cycles,
        "samples": len(samples),
        "avg_scores": avg_scores,
        "diff_scores": diff_scores,
    }


def _ticket_score(red: List[int], blue: int, actual: Dict) -> float:
    """统一评分：红球命中 + 蓝球加权命中。"""
    red_hits = len(set(red) & set(actual['red_balls']))
    blue_hit = 1 if blue == actual['blue_ball'] else 0
    return red_hits + blue_hit * 1.5


def train_lead_agent(
    records: List[Dict],
    learning_cycles: int = 24,
    learning_rate: float = 0.15,
    window_sizes: Optional[Tuple[int, ...]] = None,
    window_weights: Optional[Tuple[float, ...]] = None,
    decay_gamma: float = 0.88,  # 微调：降低增强近期权重，应对冷号回补现象
    initial_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Dict[str, float]]:
    """主Agent差异学习：多窗口回测 + 时间衰减动态赋权。"""
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
        weights = {agent: max(0.05, initial_normalized[agent] * len(AGENT_TEAMS)) for agent in AGENT_TEAMS}
    else:
        weights = {agent: 1.0 for agent in AGENT_TEAMS}
    avg_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    diff_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    window_reports = []
    active_weight_total = 0.0

    for idx, cycles in enumerate(valid_windows):
        report = _window_agent_performance(records, cycles=cycles, decay_gamma=decay_gamma)
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

    if active_weight_total <= 0:
        normalized = {agent: 1 / len(AGENT_TEAMS) for agent in AGENT_TEAMS}
        return {
            "weights": normalized,
            "avg_scores": avg_scores,
            "diff_scores": diff_scores,
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
        weights[agent] = max(0.05, 1.0 + learning_rate * diff_scores[agent])

    total = sum(weights.values())
    normalized = {agent: weight / total for agent, weight in weights.items()}
    return {
        "weights": normalized,
        "avg_scores": avg_scores,
        "diff_scores": diff_scores,
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
                red, blue = generate_prediction(history, strategy=agent, rng=random.Random())
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
    return os.path.join(ARCHIVE_DIR, f"{target_period}.txt")


def save_compact_prediction(
    target_period: str,
    tickets: List[Dict[str, object]],
    lead_summary: str,
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
    lines = [
        f"period={target_period}",
        f"generated_at={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"ticket_count={len(tickets)}",
        f"lead_summary={lead_summary}",
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


def next_target_period(records: List[Dict]) -> str:
    if not records:
        return datetime.now().strftime("%Y%m%d")
    latest = str(records[0].get("period", "")).strip()
    if latest.isdigit():
        return str(int(latest) + 1)
    return f"{latest}_next"


def main():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description='双色球预测工具')
    parser.add_argument('--mode', '-m', default='team', choices=['single', 'team'],
                       help='预测模式：single=单策略，team=多Agent团队')
    parser.add_argument('--strategy', '-s', default='balanced',
                       choices=['hot', 'cold', 'missing', 'balanced', 'random', 'cycle', 'sum', 'zone', 'lstm'],
                       help='预测策略（新增：cycle=周期性, sum=和值趋势, zone=区间平衡, lstm=神经网络）')
    parser.add_argument('--num', '-n', type=int, default=5,
                       help='生成注数')
    parser.add_argument('--all', '-a', action='store_true',
                       help='使用所有策略')
    parser.add_argument('--learn-cycles', type=int, default=24,
                       help='主Agent差异学习回看期数（仅team模式生效）')
    parser.add_argument('--seed', type=int, default=None,
                       help='随机种子（用于复现实验）')
    parser.add_argument('--weight-patch', default=None,
                       help='权重补丁文件路径（来自 analyze_archive 导出的 weight_patch.json）')
    parser.add_argument('--advanced', '-adv', action='store_true',
                       help='使用高级综合分析（时间加权+关联分析+模式识别+遗传算法）')
    
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
    
    # 分析数据
    analysis = analyze_hot_cold(records)
    print(f"\n🔥 热号TOP10: {' '.join([f'{n:02d}' for n in analysis['hot_red']])}")
    print(f"❄️ 冷号BOTTOM10: {' '.join([f'{n:02d}' for n in analysis['cold_red']])}")
    
    # 生成预测
    print("\n" + "=" * 60)
    print("🎯 预测号码")
    print("=" * 60)

    if args.mode == 'team':
        latest_archive = load_latest_archive()
        gap_result = evaluate_last_prediction_gap(latest_archive, records[0])
        resolved_patch_path, patch_source = resolve_weight_patch_path(args.weight_patch)
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
        print("👑 主Agent学习权重:")
        for agent, weight in sorted(lead_model["weights"].items(), key=lambda x: x[1], reverse=True):
            diff = lead_model["diff_scores"][agent]
            print(f"  - {agent:8s} 权重 {weight:.3f} | 差异均值 {diff:+.3f}")

        expert_teams = build_expert_teams(records, tickets=args.num, seed=args.seed)
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
        final_tickets = []
        for i in range(args.num):
            final_ticket = judge_with_lead_agent(
                expert_teams,
                lead_model=lead_model,
                diff_factor=diff_factor,
                ticket_index=i,
                seed=args.seed,
                existing_tickets=final_tickets,
            )
            if not final_ticket:
                red, blue = generate_team_prediction(records, lead_model, rng=rng)
                sources = []
                explain = "来源Agent=fallback;红球贡献=na;蓝球贡献=na;多样性替换=无"
                explain_json = {
                    "sources": ["fallback"],
                    "red": [],
                    "blue": {"ball": int(blue), "top_agent": "fallback", "top_contribution": 0.0, "agent_contributions": {}},
                    "diversity_replacements": [],
                }
            else:
                red, blue = final_ticket["red"], final_ticket["blue"]
                sources = final_ticket["sources"]
                explain = final_ticket.get("explain", "")
                explain_json = final_ticket.get("explain_json")
            source_text = ",".join(sources) if sources else "fallback"
            print(f"  第{i+1}注: 红球 {' '.join([f'{b:02d}' for b in red])} + 蓝球 {blue:02d} | 来源 {source_text}")
            final_tickets.append({
                "red": red,
                "blue": blue,
                "sources": sources or ["fallback"],
                "explain": explain,
                "explain_json": explain_json,
            })
        summary = build_archive_lead_summary(diff_factor, lead_report, patch_source=patch_source)
        saved_path = save_compact_prediction(target_period, final_tickets, summary)
        print(f"\n💾 已归档本期精简预测: {saved_path}")
    else:
        strategies = ['hot', 'cold', 'missing', 'balanced', 'random', 'cycle', 'sum', 'zone', 'lstm'] if args.all else [args.strategy]
        strategy_names = {
            'hot': '追热策略',
            'cold': '追冷策略',
            'missing': '高遗漏策略',
            'balanced': '平衡策略',
            'random': '完全随机',
            'cycle': '周期性策略',
            'sum': '和值趋势策略',
            'zone': '区间平衡策略',
            'lstm': 'LSTM神经网络策略'
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
                    red, blue = generate_prediction(records, strategy, rng=rng)
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
    # 2. 号码关联分析（马尔可夫链 + 共现分析）
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
        
        def __init__(self, analyzer: 'AdvancedAnalyzer', population_size: int = 50, generations: int = 30):
            self.analyzer = analyzer
            self.population_size = population_size
            self.generations = generations
            self.records = analyzer.records
            
            # 预计算历史数据用于适应度评估
            self.historical_sets = [set(r['red_balls']) for r in self.records[:50]]
        
        def create_individual(self, rng: random.Random) -> Set[int]:
            """创建一个个体（6个红球）"""
            return set(rng.sample(range(1, 34), 6))
        
        def fitness(self, individual: Set[int]) -> float:
            """适应度函数：与历史开奖的重合度"""
            if not self.historical_sets:
                return 0.5
            
            # 计算与历史开奖的平均重合度
            total_score = 0
            for historical in self.historical_sets:
                intersection = len(individual & historical)
                # 奖励 2-4 个重合（实际中奖范围）
                if 2 <= intersection <= 4:
                    total_score += intersection * 0.3
                else:
                    total_score += intersection * 0.1
            
            avg_score = total_score / len(self.historical_sets)
            
            # 额外奖励：包含热号和冷号的平衡
            hot_cold_bonus = self._hot_cold_balance_bonus(individual)
            
            return avg_score + hot_cold_bonus
        
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
        
        # 2. 关联分析
        print("\n🔗 2. 号码关联分析...")
        correlation = self.analyze_number_correlation()
        if correlation['top_pairs']:
            print(f"   高频关联对: {correlation['top_pairs'][:5]}")
        
        # 3. 模式识别
        print("\n🎯 3. 模式识别分析...")
        patterns = self.analyze_patterns(recent_periods=20)
        print(f"   常见奇偶比: {patterns['odd_even_freq'][:3]}")
        print(f"   常见大小比: {patterns['big_small_freq'][:3]}")
        print(f"   平均和值: {patterns['avg_sum']:.1f} ± {patterns['sum_std']:.1f}")
        
        # 4. 遗传算法优化
        print("\n🧬 4. 遗传算法优化...")
        ga = self.GeneticOptimizer(self, population_size=30, generations=20)
        ga_result = ga.optimize()
        print(f"   遗传算法推荐: {ga_result}")
        
        return {
            'time_weighted': time_weighted,
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
    
    # 整合多种方法生成红球
    red_candidates = set()
    
    # 1. 加入时间加权高分号码
    time_top = [n for n, _ in analysis['time_weighted']['top_red'][:8]]
    red_candidates.update(time_top[:4])
    
    # 2. 加入遗传算法结果
    red_candidates.update(analysis['genetic_result'][:3])
    
    # 3. 加入关联分析中的高频对
    if analysis['correlation']['top_pairs']:
        for (a, b), count in analysis['correlation']['top_pairs'][:3]:
            red_candidates.add(a)
            red_candidates.add(b)
    
    # 4. 根据模式补充
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
        # 补充号码
        all_numbers = set(range(1, 34)) - set(red_balls)
        red_balls.extend(rng.sample(list(all_numbers), 6 - len(red_balls)))
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
