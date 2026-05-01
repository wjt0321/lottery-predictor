#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强分析模块
融合扩展数据（销售额/奖池/中奖注数）和可视化分析结果到预测算法
"""

import json
import os
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Optional
import math


def analyze_pool_influence(records, recent_periods=20):
    """
    分析奖池金额对号码分布的影响
    大奖池时，号码分布是否有特定规律？
    """
    if len(records) < recent_periods:
        return {'pool_weights': {n: 1.0 for n in range(1, 34)}, 'pool_blue_weights': {n: 1.0 for n in range(1, 17)}, 'has_data': False}
    
    recent = records[:recent_periods]
    
    # 检查是否有奖池数据
    has_pool_data = any(r.get('pool', 0) > 0 for r in recent)
    
    if not has_pool_data:
        # 没有奖池数据，返回中性权重
        return {
            'pool_weights': {n: 1.0 for n in range(1, 34)},
            'pool_blue_weights': {n: 1.0 for n in range(1, 17)},
            'has_data': False,
            'note': '当前数据不包含奖池信息，请运行 update_data.py 更新最新数据'
        }
    
    # 分离大奖池期和小奖池期
    high_pool_records = []
    low_pool_records = []
    
    for r in recent:
        pool = r.get('pool', 0)
        if pool > 0:
            # 奖池大于1亿视为大奖池
            if pool > 100000000:
                high_pool_records.append(r)
            else:
                low_pool_records.append(r)
    
    if not high_pool_records or not low_pool_records:
        return {
            'pool_weights': {n: 1.0 for n in range(1, 34)},
            'pool_blue_weights': {n: 1.0 for n in range(1, 17)},
            'has_data': has_pool_data,
            'high_pool_count': len(high_pool_records),
            'low_pool_count': len(low_pool_records)
        }
    
    # 统计大奖池期的号码频率
    high_pool_red = Counter()
    high_pool_blue = Counter()
    for r in high_pool_records:
        high_pool_red.update(r['red_balls'])
        high_pool_blue.update([r['blue_ball']])
    
    # 统计小奖池期的号码频率
    low_pool_red = Counter()
    low_pool_blue = Counter()
    for r in low_pool_records:
        low_pool_red.update(r['red_balls'])
        low_pool_blue.update([r['blue_ball']])
    
    # 计算差异权重（大奖池期更可能出现的号码权重更高）
    pool_weights = {}
    for num in range(1, 34):
        high_freq = high_pool_red.get(num, 0) / len(high_pool_records) if high_pool_records else 0
        low_freq = low_pool_red.get(num, 0) / len(low_pool_records) if low_pool_records else 0
        
        # 如果大奖池期出现频率明显高于小奖池期，提高权重
        if low_freq > 0:
            ratio = high_freq / low_freq
            pool_weights[num] = min(2.0, max(0.5, ratio))
        else:
            pool_weights[num] = 1.5 if high_freq > 0 else 1.0
    
    pool_blue_weights = {}
    for num in range(1, 17):
        high_freq = high_pool_blue.get(num, 0) / len(high_pool_records) if high_pool_records else 0
        low_freq = low_pool_blue.get(num, 0) / len(low_pool_records) if low_pool_records else 0
        
        if low_freq > 0:
            ratio = high_freq / low_freq
            pool_blue_weights[num] = min(2.0, max(0.5, ratio))
        else:
            pool_blue_weights[num] = 1.5 if high_freq > 0 else 1.0
    
    return {
        'pool_weights': pool_weights,
        'pool_blue_weights': pool_blue_weights,
        'has_data': True,
        'high_pool_count': len(high_pool_records),
        'low_pool_count': len(low_pool_records)
    }


def analyze_sales_influence(records, recent_periods=20):
    """
    分析销售额对号码分布的影响
    高销售额期是否有特定规律？
    """
    if len(records) < recent_periods:
        return {'sales_weights': {n: 1.0 for n in range(1, 34)}, 'has_data': False}
    
    recent = records[:recent_periods]
    
    # 检查是否有销售额数据
    sales_list = [r.get('sales', 0) for r in recent if r.get('sales', 0) > 0]
    
    if not sales_list:
        return {
            'sales_weights': {n: 1.0 for n in range(1, 34)},
            'has_data': False,
            'note': '当前数据不包含销售额信息，请运行 update_data.py 更新最新数据'
        }
    
    avg_sales = sum(sales_list) / len(sales_list)
    
    # 分离高销售额期和低销售额期
    high_sales_records = [r for r in recent if r.get('sales', 0) > avg_sales]
    low_sales_records = [r for r in recent if r.get('sales', 0) <= avg_sales and r.get('sales', 0) > 0]
    
    if not high_sales_records or not low_sales_records:
        return {
            'sales_weights': {n: 1.0 for n in range(1, 34)},
            'has_data': True,
            'avg_sales': avg_sales,
            'high_sales_count': len(high_sales_records)
        }
    
    # 统计号码频率差异
    high_sales_red = Counter()
    for r in high_sales_records:
        high_sales_red.update(r['red_balls'])
    
    low_sales_red = Counter()
    for r in low_sales_records:
        low_sales_red.update(r['red_balls'])
    
    sales_weights = {}
    for num in range(1, 34):
        high_freq = high_sales_red.get(num, 0) / len(high_sales_records)
        low_freq = low_sales_red.get(num, 0) / len(low_sales_records)
        
        if low_freq > 0:
            ratio = high_freq / low_freq
            sales_weights[num] = min(1.5, max(0.7, ratio))
        else:
            sales_weights[num] = 1.3 if high_freq > 0 else 1.0
    
    return {
        'sales_weights': sales_weights,
        'has_data': True,
        'avg_sales': avg_sales,
        'high_sales_count': len(high_sales_records)
    }


def analyze_visual_patterns(records, recent_periods=30):
    """
    基于可视化分析发现的模式
    1. 连号模式检测
    2. 同尾号模式检测
    3. 号码聚集度分析
    """
    if len(records) < 5:
        return {
            'consecutive_patterns': [],
            'same_tail_patterns': [],
            'cluster_scores': {n: 1.0 for n in range(1, 34)}
        }
    
    recent = records[:recent_periods]
    
    # 1. 连号模式检测
    consecutive_patterns = Counter()
    for r in recent:
        balls = sorted(r['red_balls'])
        for i in range(len(balls) - 1):
            if balls[i+1] == balls[i] + 1:
                consecutive_patterns[(balls[i], balls[i+1])] += 1
    
    # 2. 同尾号模式检测
    same_tail_patterns = Counter()
    for r in recent:
        balls = r['red_balls']
        tails = defaultdict(list)
        for b in balls:
            tails[b % 10].append(b)
        for tail, nums in tails.items():
            if len(nums) >= 2:
                same_tail_patterns[tuple(sorted(nums))] += 1
    
    # 3. 号码聚集度分析（哪些号码倾向于一起出现）
    cooccurrence = defaultdict(lambda: defaultdict(int))
    for r in recent:
        balls = r['red_balls']
        for i, b1 in enumerate(balls):
            for b2 in balls[i+1:]:
                cooccurrence[b1][b2] += 1
                cooccurrence[b2][b1] += 1
    
    # 计算聚集度得分
    cluster_scores = {}
    for num in range(1, 34):
        if num in cooccurrence:
            total_cooccur = sum(cooccurrence[num].values())
            avg_cooccur = total_cooccur / len(cooccurrence[num]) if cooccurrence[num] else 0
            cluster_scores[num] = min(2.0, 1.0 + avg_cooccur * 0.1)
        else:
            cluster_scores[num] = 1.0
    
    return {
        'consecutive_patterns': consecutive_patterns.most_common(5),
        'same_tail_patterns': same_tail_patterns.most_common(5),
        'cluster_scores': cluster_scores
    }


def calculate_enhanced_weights(records, strategy='balanced'):
    """
    计算增强权重，融合扩展数据和可视化分析
    返回每个号码的综合权重
    """
    # 获取各种分析结果
    pool_analysis = analyze_pool_influence(records)
    sales_analysis = analyze_sales_influence(records)
    visual_analysis = analyze_visual_patterns(records)
    
    # 综合权重计算 - 使用加权求和避免极端值
    red_weights = {}
    for num in range(1, 34):
        pool_w = pool_analysis['pool_weights'].get(num, 1.0)
        sales_w = sales_analysis['sales_weights'].get(num, 1.0)
        cluster_w = visual_analysis['cluster_scores'].get(num, 1.0)
        # 加权求和 + 中心化，范围限制在 [0.7, 1.5]
        weight = (pool_w * 0.4 + sales_w * 0.2 + cluster_w * 0.4)
        weight = max(0.7, min(1.5, weight))
        red_weights[num] = weight
    
    # 蓝球权重
    blue_weights = {}
    for num in range(1, 17):
        weight = pool_analysis['pool_blue_weights'].get(num, 1.0)
        weight = max(0.7, min(1.5, weight))
        blue_weights[num] = weight
    
    return {
        'red_weights': red_weights,
        'blue_weights': blue_weights,
        'pool_analysis': pool_analysis,
        'sales_analysis': sales_analysis,
        'visual_analysis': visual_analysis
    }


def apply_enhanced_weights(candidates, weights, top_n=15):
    """
    将增强权重应用到候选号码上
    返回加权排序后的候选号码
    """
    weighted_candidates = []
    for num in candidates:
        weight = weights.get(num, 1.0)
        weighted_candidates.append((num, weight))
    
    # 按权重排序
    weighted_candidates.sort(key=lambda x: x[1], reverse=True)
    return [num for num, _ in weighted_candidates[:top_n]]


# ============================================================================
# 与predict.py集成的接口函数
# ============================================================================

def get_enhanced_candidates(records, base_candidates, is_red=True):
    """
    获取增强后的候选号码
    用于在generate_prediction中替换原始候选
    """
    enhanced = calculate_enhanced_weights(records)
    
    if is_red:
        weights = enhanced['red_weights']
    else:
        weights = enhanced['blue_weights']
    
    return apply_enhanced_weights(base_candidates, weights)


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("🔬 增强分析模块测试")
    print("=" * 60)
    
    try:
        with open('lottery_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        records = data.get('records', [])
        print(f"\n📊 加载了 {len(records)} 期数据")
        
        # 测试奖池分析
        print("\n💰 奖池影响分析:")
        pool_result = analyze_pool_influence(records)
        if pool_result.get('has_data'):
            print(f"   大奖池期数: {pool_result.get('high_pool_count', 0)}")
            print(f"   小奖池期数: {pool_result.get('low_pool_count', 0)}")
            top_pool = sorted(pool_result['pool_weights'].items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"   大奖池高权重号码: {top_pool}")
        else:
            print(f"   ⚠️ {pool_result.get('note', '数据不可用')}")
        
        # 测试销售额分析
        print("\n💵 销售额影响分析:")
        sales_result = analyze_sales_influence(records)
        if sales_result.get('has_data'):
            print(f"   平均销售额: {sales_result.get('avg_sales', 0):,.0f}")
            print(f"   高销售额期数: {sales_result.get('high_sales_count', 0)}")
        else:
            print(f"   ⚠️ {sales_result.get('note', '数据不可用')}")
        
        # 测试可视化模式分析
        print("\n📈 可视化模式分析:")
        visual_result = analyze_visual_patterns(records)
        print(f"   常见连号模式: {visual_result['consecutive_patterns'][:3]}")
        print(f"   常见同尾号模式: {visual_result['same_tail_patterns'][:3]}")
        
        # 测试综合权重
        print("\n⚖️ 综合权重计算:")
        weights = calculate_enhanced_weights(records)
        top_red = sorted(weights['red_weights'].items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"   红球Top10权重: {top_red}")
        
        print("\n✅ 增强分析模块测试完成")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
