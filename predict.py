#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预测脚本：支持单策略与多 Agent 团队协同预测。"""

import argparse
import json
import os
import random
import sys
from collections import Counter
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple


DATA_FILE = "lottery_data.json"
ARCHIVE_DIR = "prediction_archive"
AGENT_TEAMS = ("hot", "cold", "missing", "balanced", "random")


def load_data():
    """加载数据"""
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze_hot_cold(records, recent_periods=30):
    """冷热号分析 - 优化：增加蓝球冷号分析"""
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
    """按单策略生成预测号码 - 优化：增加蓝球遗漏分析和趋势权重"""
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


def _ticket_score(red: List[int], blue: int, actual: Dict) -> float:
    """统一评分：红球命中 + 蓝球加权命中。"""
    red_hits = len(set(red) & set(actual['red_balls']))
    blue_hit = 1 if blue == actual['blue_ball'] else 0
    return red_hits + blue_hit * 1.5


def train_lead_agent(
    records: List[Dict], learning_cycles: int = 24, learning_rate: float = 0.15
) -> Dict[str, Dict[str, float]]:
    """主Agent差异学习：根据近期回测对团队Agent动态赋权。"""
    weights = {agent: 1.0 for agent in AGENT_TEAMS}
    avg_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    diff_scores = {agent: 0.0 for agent in AGENT_TEAMS}
    rounds = 0

    for history_timeline, target in iterate_archived_cycles(records, cycles=learning_cycles):
        history = list(reversed(history_timeline))
        per_round_scores = {}
        for agent in AGENT_TEAMS:
            red, blue = generate_prediction(history, strategy=agent, rng=random.Random())
            per_round_scores[agent] = _ticket_score(red, blue, target)

        team_avg = sum(per_round_scores.values()) / len(per_round_scores)
        for agent, score in per_round_scores.items():
            avg_scores[agent] += score
            diff = score - team_avg
            diff_scores[agent] += diff
            weights[agent] = max(0.05, weights[agent] + learning_rate * diff)
        rounds += 1

    if rounds == 0:
        normalized = {agent: 1 / len(AGENT_TEAMS) for agent in AGENT_TEAMS}
        return {"weights": normalized, "avg_scores": avg_scores, "diff_scores": diff_scores}

    for agent in AGENT_TEAMS:
        avg_scores[agent] /= rounds
        diff_scores[agent] /= rounds

    total = sum(weights.values())
    normalized = {agent: weight / total for agent, weight in weights.items()}
    return {"weights": normalized, "avg_scores": avg_scores, "diff_scores": diff_scores}


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
    for index, ticket in enumerate(tickets, start=1):
        red_text = " ".join(f"{n:02d}" for n in ticket["red"])
        blue_text = f"{int(ticket['blue']):02d}"
        source_text = ",".join(ticket.get("sources", []))
        ticket_lines.append(f"ticket{index}={red_text}+{blue_text}|{source_text}")
    lines = [
        f"period={target_period}",
        f"generated_at={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"ticket_count={len(tickets)}",
        f"lead_summary={lead_summary}",
        *ticket_lines,
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
) -> Optional[Dict[str, object]]:
    red_scores = {i: 0.0 for i in range(1, 34)}
    blue_scores = {i: 0.0 for i in range(1, 17)}
    red_sources, blue_sources = _ball_sources(teams, ticket_index)
    valid_agents: List[str] = []

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
            red_scores[red] += final_weight * (1 + agreement_bonus)
        blue = proposal["blue"]
        agreement_bonus = len(blue_sources.get(blue, [])) * 0.1
        blue_scores[blue] += final_weight * (1 + agreement_bonus)

    if not valid_agents:
        return None
    rng = random.Random((seed or random.randint(1, 999999)) + ticket_index * 17)
    final_red = _weighted_unique_sample(red_scores, 6, rng)
    final_blue = _weighted_choice(blue_scores, rng)
    source_agents = sorted(set(red_sources.get(ball, [])[0] for ball in final_red if red_sources.get(ball)))
    if final_blue in blue_sources:
        source_agents.extend(blue_sources[final_blue])
    source_agents = sorted(set(source_agents))
    return {
        "red": final_red,
        "blue": final_blue,
        "sources": source_agents or valid_agents,
        "valid_agents": sorted(valid_agents),
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
                       choices=['hot', 'cold', 'missing', 'balanced', 'random'],
                       help='预测策略')
    parser.add_argument('--num', '-n', type=int, default=5,
                       help='生成注数')
    parser.add_argument('--all', '-a', action='store_true',
                       help='使用所有策略')
    parser.add_argument('--learn-cycles', type=int, default=24,
                       help='主Agent差异学习回看期数（仅team模式生效）')
    parser.add_argument('--seed', type=int, default=None,
                       help='随机种子（用于复现实验）')
    
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
        lead_model = train_lead_agent(records, learning_cycles=args.learn_cycles)
        diff_factor = float(gap_result["factor"])
        print(f"\n🤖 多Agent团队模式（回看 {args.learn_cycles} 期进行差异学习）")
        print(f"🧠 主Agent差异学习: {gap_result['summary']}")
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
            )
            if not final_ticket:
                red, blue = generate_team_prediction(records, lead_model, rng=rng)
                sources = []
            else:
                red, blue = final_ticket["red"], final_ticket["blue"]
                sources = final_ticket["sources"]
            source_text = ",".join(sources) if sources else "fallback"
            print(f"  第{i+1}注: 红球 {' '.join([f'{b:02d}' for b in red])} + 蓝球 {blue:02d} | 来源 {source_text}")
            final_tickets.append({
                "red": red,
                "blue": blue,
                "sources": sources or ["fallback"],
            })
        summary = f"factor={diff_factor:.2f};mode=team;agents={','.join(lead_report['healthy_agents'])};report={lead_report['archive_summary']}"
        saved_path = save_compact_prediction(target_period, final_tickets, summary)
        print(f"\n💾 已归档本期精简预测: {saved_path}")
    else:
        strategies = ['hot', 'cold', 'missing', 'balanced', 'random'] if args.all else [args.strategy]
        strategy_names = {
            'hot': '追热策略',
            'cold': '追冷策略',
            'missing': '高遗漏策略',
            'balanced': '平衡策略',
            'random': '完全随机'
        }

        for strategy in strategies:
            name = strategy_names.get(strategy, strategy)
            print(f"\n{name}:")

            for i in range(args.num):
                red, blue = generate_prediction(records, strategy, rng=rng)
                print(f"  第{i+1}注: 红球 {' '.join([f'{b:02d}' for b in red])} + 蓝球 {blue:02d}")
    
    print("\n" + "=" * 60)
    print("⚠️ 仅供娱乐，不构成投注建议！")
    print("=" * 60)


if __name__ == "__main__":
    main()
