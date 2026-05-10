#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立蓝球预测引擎 (Blue Ball Engine)

不再依附于红球策略 Agent，独立对 16 个蓝球进行多维度分析：
1. 遗漏值分析（冷号追号）
2. 奇偶轮动周期
3. 区间转移矩阵
4. 振幅分析
5. 贝叶斯概率更新
6. 热度加权

输出：蓝球得分排行 + 推荐候选池
"""

import json
import os
import math
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple


class BlueBallEngine:
    """独立蓝球预测引擎"""

    def __init__(self, records: List[Dict], config: Optional[Dict] = None):
        self.records = records
        self.blue_range = range(1, 17)
        self.config = config or {}

        # 可调参数
        self.missing_cold_threshold = self.config.get("missing_cold_threshold", 20)
        self.missing_cold_bonus = self.config.get("missing_cold_bonus", 1.8)
        self.missing_extreme_threshold = self.config.get("missing_extreme_threshold", 40)
        self.missing_extreme_bonus = self.config.get("missing_extreme_bonus", 2.5)
        self.parity_window = self.config.get("parity_window", 15)
        self.zone_window = self.config.get("zone_window", 30)
        self.amplitude_window = self.config.get("amplitude_window", 30)
        self.heat_window = self.config.get("heat_window", 20)
        self.cold_chase_cap = self.config.get("cold_chase_cap", 3)

    # =========================================================================
    # 1. 遗漏值分析（冷号追号）
    # =========================================================================
    def analyze_missing(self) -> Dict[int, int]:
        """计算每个蓝球的遗漏期数"""
        last_seen = {}
        for idx, r in enumerate(self.records):
            blue = r['blue_ball']
            if blue not in last_seen:
                last_seen[blue] = idx

        missing = {}
        for num in self.blue_range:
            if num not in last_seen:
                missing[num] = len(self.records)
            else:
                missing[num] = last_seen[num]
        return missing

    def missing_score(self, missing: Dict[int, int]) -> Dict[int, float]:
        """遗漏值打分：冷号加权追号"""
        scores = {}
        for num, miss in missing.items():
            if miss >= self.missing_extreme_threshold:
                scores[num] = self.missing_extreme_bonus
            elif miss >= self.missing_cold_threshold:
                # 线性插值：20期开始加权，越冷越高
                ratio = min(1.0, (miss - self.missing_cold_threshold) /
                           (self.missing_extreme_threshold - self.missing_cold_threshold))
                scores[num] = 1.0 + ratio * (self.missing_extreme_bonus - 1.0)
            elif miss <= 3:
                scores[num] = 0.8  # 刚出过，略微降权
            else:
                scores[num] = 1.0
        return scores

    # =========================================================================
    # 2. 奇偶轮动分析
    # =========================================================================
    def analyze_parity_cycle(self) -> Tuple[float, List[int]]:
        """分析蓝球奇偶轮动周期"""
        if len(self.records) < 5:
            return 0.5, []

        recent = self.records[:self.parity_window]
        blues = [r['blue_ball'] for r in recent]
        parity_seq = [b % 2 for b in blues]

        odd_count = sum(parity_seq)
        even_count = len(parity_seq) - odd_count
        overall_odd_ratio = odd_count / len(parity_seq) if parity_seq else 0.5

        # 近期 10 期奇偶比
        recent10 = parity_seq[:10] if len(parity_seq) >= 10 else parity_seq
        recent_odd_ratio = sum(recent10) / len(recent10) if recent10 else 0.5

        # 回均修正
        reversion = 0.5 - recent_odd_ratio
        next_odd_prob = 0.5 + reversion * 0.4
        next_odd_prob = max(0.3, min(0.7, next_odd_prob))

        # 奇偶连续数检测
        parity_runs = []
        run = 1
        for i in range(1, min(15, len(parity_seq))):
            if parity_seq[i] == parity_seq[i - 1]:
                run += 1
            else:
                parity_runs.append(run)
                run = 1
        parity_runs.append(run)
        max_run = max(parity_runs) if parity_runs else 1

        # 连续同奇偶超过 4 期 → 加大反转概率
        if max_run >= 4:
            last_parity = parity_seq[0]
            if last_parity == 1:
                next_odd_prob = max(0.1, next_odd_prob - 0.15)
            else:
                next_odd_prob = min(0.9, next_odd_prob + 0.15)

        return next_odd_prob, parity_seq[:15]

    # =========================================================================
    # 3. 区间转移矩阵（1-5, 6-10, 11-16）
    # =========================================================================
    def analyze_zone_transition(self) -> Dict[int, Tuple[float, float, float]]:
        """蓝球区间转移矩阵"""
        if len(self.records) < 5:
            default = (1 / 3, 1 / 3, 1 / 3)
            return {num: default for num in self.blue_range}

        def blue_zone(b):
            if b <= 5:
                return 0
            if b <= 10:
                return 1
            return 2

        recent = self.records[:self.zone_window]
        blues = [r['blue_ball'] for r in recent]
        zone_seq = [blue_zone(b) for b in blues]

        # 构建转移矩阵
        zone_trans = [[1, 1, 1], [1, 1, 1], [1, 1, 1]]
        for i in range(1, len(zone_seq)):
            zone_trans[zone_seq[i - 1]][zone_seq[i]] += 1

        # 拉普拉斯平滑归一化
        for z in range(3):
            row_sum = sum(zone_trans[z])
            for t in range(3):
                zone_trans[z][t] /= row_sum

        last_zone = zone_seq[0]
        next_zone_probs = tuple(zone_trans[last_zone])

        # 返回每个蓝球对应区间的概率
        result = {}
        for num in self.blue_range:
            zone = blue_zone(num)
            # 基础概率 = 转移概率，同时考虑各区的静态分布
            zone_priors = [0.33, 0.33, 0.34]
            zone_count = Counter(zone_seq)
            for z in range(3):
                zone_priors[z] = zone_count.get(z, 0) / len(zone_seq)
            result[num] = (
                next_zone_probs[0],
                next_zone_probs[1],
                next_zone_probs[2],
            )
        return result

    # =========================================================================
    # 4. 振幅分析
    # =========================================================================
    def analyze_amplitude(self) -> Dict[int, float]:
        """分析蓝球振幅（相邻两期差值的绝对值）"""
        if len(self.records) < 5:
            return {num: 1.0 for num in self.blue_range}

        recent = self.records[:self.amplitude_window]
        blues = [r['blue_ball'] for r in recent]

        amplitudes = []
        for i in range(len(blues) - 1):
            amplitudes.append(abs(blues[i] - blues[i + 1]))

        if not amplitudes:
            return {num: 1.0 for num in self.blue_range}

        avg_amp = sum(amplitudes) / len(amplitudes)
        std_amp = math.sqrt(
            sum((a - avg_amp) ** 2 for a in amplitudes) / len(amplitudes)
        ) if len(amplitudes) > 1 else 5.0

        # 最近一期蓝球
        last_blue = blues[0]

        # 对每个候选蓝球计算振幅匹配度
        scores = {}
        for num in self.blue_range:
            amp = abs(num - last_blue)
            # 振幅接近均值 → 高分
            z_score = abs(amp - avg_amp) / (std_amp + 1)
            scores[num] = math.exp(-0.3 * z_score)

        return scores

    # =========================================================================
    # 5. 热度分析
    # =========================================================================
    def analyze_heat(self) -> Dict[int, float]:
        """短期热度分析"""
        if len(self.records) < 3:
            return {num: 1.0 for num in self.blue_range}

        recent = self.records[:self.heat_window]
        blue_freq = Counter(r['blue_ball'] for r in recent)

        max_freq = max(blue_freq.values()) if blue_freq else 1
        scores = {}
        for num in self.blue_range:
            freq = blue_freq.get(num, 0)
            scores[num] = 0.5 + (freq / max_freq) * 1.0

        return scores

    # =========================================================================
    # 6. 贝叶斯概率更新（基于历史先验 → 条件更新）
    # =========================================================================
    def bayesian_update(self, base_scores: Dict[int, float],
                        last_n: int = 5) -> Dict[int, float]:
        """贝叶斯思路：以 base_scores 为先验，用最近 N 期模式更新"""
        updated = dict(base_scores)

        if len(self.records) < last_n:
            return updated

        recent_blues = [r['blue_ball'] for r in self.records[:last_n]]
        recent_set = set(recent_blues)

        # 近期重复号惩罚
        repeat_count = Counter(recent_blues)
        for num, cnt in repeat_count.items():
            if cnt >= 2:
                updated[num] *= 0.7

        # 近期完全没出的号 → 微小加成
        for num in self.blue_range:
            if num not in recent_set:
                updated[num] *= 1.05

        return updated

    # =========================================================================
    # 综合预测
    # =========================================================================
    def predict(self, pool_size: int = 6) -> Dict:
        """综合所有维度输出蓝球预测结果

        Returns:
            {
                'scores': {1: 1.2, 2: 0.9, ...},
                'pool': [3, 7, 14, ...],  # 推荐候选池
                'details': {...},  # 各维度详情
                'cold_chase': [...]  # 追冷推荐
            }
        """
        # 逐个维度分析
        missing = self.analyze_missing()
        missing_scores = self.missing_score(missing)
        next_odd_prob, parity_seq = self.analyze_parity_cycle()
        zone_probs = self.analyze_zone_transition()
        amp_scores = self.analyze_amplitude()
        heat_scores = self.analyze_heat()

        # 加权融合
        weights = {
            'missing': 0.30,   # 遗漏值权重最高（追冷）
            'parity': 0.15,    # 奇偶轮动
            'zone': 0.15,      # 区间转移
            'amplitude': 0.15, # 振幅
            'heat': 0.25,      # 短期热度
        }

        raw_scores = {}
        for num in self.blue_range:
            # 区间匹配分
            zone_idx = 0 if num <= 5 else (1 if num <= 10 else 2)
            zone_score = zone_probs[num][zone_idx]

            # 奇偶匹配分
            parity_match = next_odd_prob if num % 2 == 1 else (1 - next_odd_prob)
            parity_score = 0.5 + parity_match * 1.0

            raw_scores[num] = (
                weights['missing'] * missing_scores[num] +
                weights['parity'] * parity_score +
                weights['zone'] * zone_score +
                weights['amplitude'] * amp_scores[num] +
                weights['heat'] * heat_scores[num]
            )

        # 贝叶斯更新
        final_scores = self.bayesian_update(raw_scores)

        # 归一化
        min_s = min(final_scores.values())
        max_s = max(final_scores.values())
        span = max_s - min_s
        if span > 0.01:
            for num in final_scores:
                final_scores[num] = 0.5 + (final_scores[num] - min_s) / span * 1.0

        # 排序选池
        ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        pool = [num for num, _ in ranked[:pool_size]]

        # 追冷推荐：遗漏超过阈值的冷号
        cold_chase = sorted(
            [(num, miss) for num, miss in missing.items()
             if miss >= self.missing_cold_threshold],
            key=lambda x: x[1], reverse=True
        )[:self.cold_chase_cap]
        # 强制纳入追冷号（如果它们在候选池之外）
        for num, _ in cold_chase:
            if num not in pool and len(pool) >= pool_size:
                pool[-1] = num  # 替换最后一个
            elif num not in pool:
                pool.append(num)
        pool = list(set(pool))  # 去重
        if len(pool) < pool_size:
            # 补充
            for num, _ in ranked:
                if num not in pool:
                    pool.append(num)
                if len(pool) >= pool_size:
                    break
        pool = pool[:pool_size]

        return {
            'scores': {num: round(final_scores[num], 6) for num in self.blue_range},
            'pool': pool,
            'details': {
                'missing': {num: missing[num] for num in self.blue_range},
                'missing_scores': {num: round(missing_scores[num], 4) for num in self.blue_range},
                'next_odd_prob': round(next_odd_prob, 4),
                'parity_seq': parity_seq[:10],
                'amp_scores': {num: round(amp_scores[num], 4) for num in self.blue_range},
                'heat_scores': {num: round(heat_scores[num], 4) for num in self.blue_range},
            },
            'cold_chase': [(num, missing[num]) for num, _ in cold_chase],
        }
