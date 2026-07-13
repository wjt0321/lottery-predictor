#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
特征重要性分析模块

基于历史开奖数据，计算各统计特征与未来中奖号码的相关系数，
识别哪些特征真正具有预测价值。

零额外依赖，仅使用 Python 标准库。
"""

import json
import math
from collections import Counter
from typing import Dict, List, Tuple, Optional


def calculate_pearson_correlation(x: List[float], y: List[float]) -> Tuple[float, float]:
    """计算皮尔逊相关系数和 p 值（近似）
    
    Returns:
        (correlation, p_value_approx)
    """
    n = len(x)
    if n < 3 or len(y) != n:
        return 0.0, 1.0
    
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    denom_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    denom_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    
    if denom_x < 1e-10 or denom_y < 1e-10:
        return 0.0, 1.0
    
    r = numerator / (denom_x * denom_y)
    
    # 近似 p 值（基于 t 分布）
    if abs(r) >= 1.0:
        p_value = 0.0
    else:
        t_stat = r * math.sqrt((n - 2) / (1 - r * r))
        # 简化的 p 值估计：|t| > 2 时 p < 0.05
        p_value = max(0.0, min(1.0, 2 * (1 - min(1.0, abs(t_stat) / 3))))
    
    return r, p_value


def calculate_spearman_correlation(x: List[float], y: List[float]) -> float:
    """计算斯皮尔曼秩相关系数（对非线性关系更稳健）"""
    n = len(x)
    if n < 3 or len(y) != n:
        return 0.0
    
    def rank(data: List[float]) -> List[float]:
        """计算排名（处理 ties）"""
        sorted_indices = sorted(range(len(data)), key=lambda i: data[i])
        ranks = [0.0] * len(data)
        i = 0
        while i < len(sorted_indices):
            j = i
            while j < len(sorted_indices) and data[sorted_indices[j]] == data[sorted_indices[i]]:
                j += 1
            avg_rank = (i + j + 1) / 2.0  # 1-based average rank
            for k in range(i, j):
                ranks[sorted_indices[k]] = avg_rank
            i = j
        return ranks
    
    rank_x = rank(x)
    rank_y = rank(y)
    
    r, _ = calculate_pearson_correlation(rank_x, rank_y)
    return r


def calculate_ac_value(balls: List[int]) -> int:
    """计算 AC 值（算术复杂度）"""
    if len(balls) < 2:
        return 0
    sorted_balls = sorted(balls)
    diffs = set()
    for i in range(len(sorted_balls)):
        for j in range(i + 1, len(sorted_balls)):
            diffs.add(sorted_balls[j] - sorted_balls[i])
    return len(diffs) - (len(sorted_balls) - 1)


def calculate_entropy(frequencies: Dict[int, int], total: int) -> float:
    """计算信息熵"""
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in frequencies.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def extract_features_for_period(records: List[Dict], period_idx: int) -> Dict[str, float]:
    """为指定时期提取特征向量
    
    Args:
        records: 历史开奖记录（从新到旧排序）
        period_idx: 要分析的期数索引（0 = 最新）
    
    Returns:
        特征字典
    """
    if period_idx >= len(records) - 1:
        return {}
    
    # 当前期（作为目标的前一期）
    current = records[period_idx]
    current_red = sorted(current['red_balls'])
    
    # 历史窗口（用于计算统计特征）
    window_20 = records[period_idx:period_idx + 20] if period_idx + 20 <= len(records) else records[period_idx:]
    window_50 = records[period_idx:period_idx + 50] if period_idx + 50 <= len(records) else records[period_idx:]
    
    features = {}
    
    # 1. AC 值
    features['ac_value'] = float(calculate_ac_value(current_red))
    
    # 2. 和值
    features['sum_value'] = float(sum(current_red))
    
    # 3. 跨度
    features['span'] = float(max(current_red) - min(current_red))
    
    # 4. 奇偶比（奇数个数）
    features['odd_count'] = float(sum(1 for b in current_red if b % 2 == 1))
    
    # 5. 大小比（大号个数，>17）
    features['big_count'] = float(sum(1 for b in current_red if b > 17))
    
    # 6. 连号数
    consecutive = 0
    for i in range(len(current_red) - 1):
        if current_red[i + 1] - current_red[i] == 1:
            consecutive += 1
    features['consecutive_count'] = float(consecutive)
    
    # 7. 区间分布（1-11, 12-22, 23-33）
    zones = [0, 0, 0]
    for b in current_red:
        if b <= 11:
            zones[0] += 1
        elif b <= 22:
            zones[1] += 1
        else:
            zones[2] += 1
    features['zone_1'] = float(zones[0])
    features['zone_2'] = float(zones[1])
    features['zone_3'] = float(zones[2])
    
    # 8. 熵值（20期窗口）
    red_freq_20 = Counter()
    for r in window_20:
        red_freq_20.update(r['red_balls'])
    total_20 = sum(red_freq_20.values())
    features['entropy_20'] = calculate_entropy(red_freq_20, total_20)
    
    # 9. 熵值（50期窗口）
    if len(window_50) >= 30:
        red_freq_50 = Counter()
        for r in window_50:
            red_freq_50.update(r['red_balls'])
        total_50 = sum(red_freq_50.values())
        features['entropy_50'] = calculate_entropy(red_freq_50, total_50)
    else:
        features['entropy_50'] = features['entropy_20']
    
    # 10. 冷热指数（20期内出现频率的标准差）
    freq_values = list(red_freq_20.values())
    if freq_values:
        mean_freq = sum(freq_values) / len(freq_values)
        variance_freq = sum((f - mean_freq) ** 2 for f in freq_values) / len(freq_values)
        features['heat_std'] = math.sqrt(variance_freq)
    else:
        features['heat_std'] = 0.0
    
    # 11. 最大遗漏值（20期内）
    max_missing = 0
    for num in range(1, 34):
        missing = 0
        for r in window_20:
            if num not in r['red_balls']:
                missing += 1
            else:
                break
        max_missing = max(max_missing, missing)
    features['max_missing'] = float(max_missing)
    
    # 12. 质数个数
    primes = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31}
    features['prime_count'] = float(sum(1 for b in current_red if b in primes))
    
    # 13. 同尾数个数
    tails = Counter(b % 10 for b in current_red)
    features['same_tail_count'] = float(sum(1 for c in tails.values() if c >= 2))
    
    return features


def compute_feature_importance(records: List[Dict], min_periods: int = 50) -> List[Dict]:
    """计算各特征的重要性排名
    
    使用滑动窗口：用前 N 期的特征预测第 N+1 期的中奖结果
    
    Args:
        records: 历史开奖记录（从新到旧排序）
        min_periods: 最少需要的历史期数
    
    Returns:
        特征重要性排名列表
    """
    if len(records) < min_periods + 1:
        return []
    
    # 收集所有特征和目标变量
    feature_names = []
    feature_vectors: Dict[str, List[float]] = {}
    target_hit_scores: List[float] = []
    target_hot_overlap: List[float] = []
    
    # records 从新到旧。对每个目标期，只允许使用它之后（更旧）的记录，
    # 形成严格的 walk-forward 样本，避免把目标期或未来期放进特征窗口。
    sample_count = len(records) - min_periods

    for target_idx in range(sample_count):
        target_record = records[target_idx]
        history = records[target_idx + 1:]
        features = extract_features_for_period(history, 0)
        if not features:
            continue

        target_red = set(target_record['red_balls'])

        # 目标变量 1：最近已知一期号码对目标期的重合数。
        latest_known_red = set(history[0]['red_balls'])
        hit_score = len(latest_known_red & target_red)
        target_hit_scores.append(float(hit_score))

        # 目标变量 2：仅用目标期之前的 20 期构造热号集合。
        window_20 = history[:20]
        red_freq = Counter()
        for r in window_20:
            red_freq.update(r['red_balls'])
        hot_numbers = {num for num, _ in red_freq.most_common(10)}
        hot_overlap = len(hot_numbers & target_red)
        target_hot_overlap.append(float(hot_overlap))
        
        # 收集特征
        for name, value in features.items():
            if name not in feature_vectors:
                feature_vectors[name] = []
            feature_vectors[name].append(value)
    
    if not feature_vectors or not target_hit_scores:
        return []
    
    # 计算每个特征与目标变量的相关性
    results = []
    feature_names = sorted(feature_vectors.keys())
    
    for name in feature_names:
        values = feature_vectors[name]
        if len(values) < 10:
            continue
        
        # 与命中数的相关性
        r_hit, p_hit = calculate_pearson_correlation(values, target_hit_scores)
        
        # 与热号重合的相关性
        r_hot, p_hot = calculate_pearson_correlation(values, target_hot_overlap)
        
        # 斯皮尔曼相关系数
        s_hit = calculate_spearman_correlation(values, target_hit_scores)
        
        # 综合重要性（取两种相关系数的平均绝对值）
        importance = (abs(r_hit) + abs(s_hit)) / 2
        
        # 确定主要方向
        if abs(r_hit) >= abs(r_hot):
            primary_r = r_hit
            primary_p = p_hit
            target_desc = "下期命中数"
        else:
            primary_r = r_hot
            primary_p = p_hot
            target_desc = "热号重合数"
        
        results.append({
            'feature_name': name,
            'pearson_r': r_hit,
            'spearman_r': s_hit,
            'hot_r': r_hot,
            'importance': importance,
            'p_value': primary_p,
            'is_significant': primary_p < 0.05,
            'target_desc': target_desc,
            'sample_size': len(values),
        })
    
    # 按重要性排序
    results.sort(key=lambda x: x['importance'], reverse=True)
    return results


def get_feature_explanation(name: str) -> str:
    """获取特征的解释说明"""
    explanations = {
        'ac_value': 'AC值（算术复杂度）：号码离散程度',
        'sum_value': '和值：6个红球的总和',
        'span': '跨度：最大号与最小号的差',
        'odd_count': '奇数个数：奇偶比的一个维度',
        'big_count': '大号个数（>17）：大小比的一个维度',
        'consecutive_count': '连号组数：连续号码的数量',
        'zone_1': '第一区间个数（1-11）',
        'zone_2': '第二区间个数（12-22）',
        'zone_3': '第三区间个数（23-33）',
        'entropy_20': '20期熵值：号码分布的不确定性',
        'entropy_50': '50期熵值：长期号码分布的不确定性',
        'heat_std': '冷热指数标准差：号码出现频率的离散程度',
        'max_missing': '最大遗漏值：20期内最长未出现的期数',
        'prime_count': '质数个数：质数号码的数量',
        'same_tail_count': '同尾数组数：相同尾数的号码组数',
    }
    return explanations.get(name, name)


def generate_importance_report(ranking: List[Dict], top_k: int = 15) -> str:
    """生成特征重要性报告"""
    if not ranking:
        return "数据不足，无法计算特征重要性。"
    
    lines = []
    lines.append("=" * 70)
    lines.append("特征重要性分析（基于最近{}期数据）".format(ranking[0]['sample_size']))
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"{'排名':<4} {'特征名':<18} {'皮尔逊r':<10} {'斯皮尔曼r':<10} {'重要性':<10} {'显著性':<6} {'解释'}")
    lines.append("-" * 70)
    
    for idx, row in enumerate(ranking[:top_k], start=1):
        sig_mark = "*" if row['is_significant'] else ""
        direction = "正" if row['pearson_r'] > 0 else "负"
        explanation = get_feature_explanation(row['feature_name'])
        
        lines.append(
            f"{idx:<4} {row['feature_name']:<18} "
            f"{row['pearson_r']:+.4f}    "
            f"{row['spearman_r']:+.4f}    "
            f"{row['importance']:.4f}     "
            f"{sig_mark:<5} "
            f"{explanation}"
        )
    
    lines.append("")
    lines.append("注: * 表示 p < 0.05，统计显著")
    lines.append("")
    
    # 结论部分
    lines.append("结论与建议:")
    lines.append("-" * 70)
    
    # 找出最显著的特征
    significant = [r for r in ranking if r['is_significant']]
    if significant:
        top = significant[0]
        lines.append(f"1. 最有效的特征是【{top['feature_name']}】，重要性={top['importance']:.4f}")
        lines.append(f"   方向：{'正相关' if top['pearson_r'] > 0 else '负相关'}（与{top['target_desc']}）")
    
    # 找出负相关特征
    negative = [r for r in ranking[:top_k] if r['pearson_r'] < -0.05]
    if negative:
        names = ", ".join([r['feature_name'] for r in negative[:3]])
        lines.append(f"2. 负相关特征：{names} —— 这些特征值越高，中奖率越低")
    
    # 找出接近0的特征（噪声）
    noise = [r for r in ranking[:top_k] if r['importance'] < 0.03]
    if noise:
        names = ", ".join([r['feature_name'] for r in noise[:3]])
        lines.append(f"3. 弱相关特征（可能为噪声）：{names}")
    
    # AC值和熵值的专项分析
    ac_row = next((r for r in ranking if r['feature_name'] == 'ac_value'), None)
    entropy_row = next((r for r in ranking if r['feature_name'] == 'entropy_20'), None)
    
    if ac_row and entropy_row:
        lines.append("")
        lines.append("本次迭代特征专项分析:")
        lines.append(f"  - AC值：重要性={ac_row['importance']:.4f}，{'正相关' if ac_row['pearson_r'] > 0 else '负相关'}")
        lines.append(f"  - 熵值(20期)：重要性={entropy_row['importance']:.4f}，{'正相关' if entropy_row['pearson_r'] > 0 else '负相关'}")
        if entropy_row['pearson_r'] < 0:
            lines.append("    负相关说明：熵值越低（冷热分明），下期中奖率越高")
    
    lines.append("")
    return "\n".join(lines)


def analyze(records: List[Dict], top_k: int = 15) -> str:
    """主入口：分析特征重要性并返回报告"""
    ranking = compute_feature_importance(records)
    return generate_importance_report(ranking, top_k)


def main():
    """独立运行入口"""
    import os
    
    data_file = "lottery_data.json"
    if not os.path.isfile(data_file):
        print(f"错误：找不到数据文件 {data_file}")
        return
    
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    records = data.get("records", [])
    if len(records) < 60:
        print(f"错误：历史数据不足（只有 {len(records)} 期，需要至少 60 期）")
        return
    
    print(f"加载了 {len(records)} 期历史数据，开始分析特征重要性...\n")
    report = analyze(records)
    print(report)


if __name__ == "__main__":
    main()
