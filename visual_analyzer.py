#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化分析模块
生成本地走势图，替代截图方案
"""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime
import math

# 尝试导入matplotlib
try:
    import matplotlib
    matplotlib.use('Agg')  # 无头模式
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("⚠️ matplotlib未安装，可视化功能不可用")
    print("   安装命令: pip install matplotlib")


class VisualAnalyzer:
    """可视化分析器"""
    
    def __init__(self, records, output_dir='charts'):
        self.records = sorted(records, key=lambda x: x['date'])
        self.output_dir = output_dir
        if MATPLOTLIB_AVAILABLE:
            os.makedirs(output_dir, exist_ok=True)
    
    def _save_chart(self, filename):
        """保存图表"""
        if MATPLOTLIB_AVAILABLE:
            filepath = os.path.join(self.output_dir, filename)
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()
            print(f"   📊 已生成: {filepath}")
            return filepath
        return None
    
    # ========================================================================
    # 1. 红球冷热走势图
    # ========================================================================
    def generate_hot_cold_trend(self, top_n=10, recent_periods=50):
        """生成红球冷热走势图"""
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        recent = self.records[-recent_periods:]
        
        # 统计每期各号码出现次数
        number_trends = {i: [] for i in range(1, 34)}
        periods = []
        
        for record in recent:
            periods.append(record['period'])
            for num in range(1, 34):
                number_trends[num].append(1 if num in record['red_balls'] else 0)
        
        # 计算总频率，找出top_n
        total_freq = Counter()
        for record in recent:
            total_freq.update(record['red_balls'])
        
        top_numbers = [n for n, _ in total_freq.most_common(top_n)]
        
        # 绘制
        fig, ax = plt.subplots(figsize=(14, 6))
        
        for num in top_numbers:
            # 计算累积频率（滑动窗口）
            window_size = 5
            smoothed = []
            for i in range(len(number_trends[num])):
                start = max(0, i - window_size + 1)
                window = number_trends[num][start:i+1]
                smoothed.append(sum(window) / len(window) * 100)
            
            ax.plot(range(len(periods)), smoothed, label=f'{num:02d}', linewidth=1.5)
        
        ax.set_xlabel('期数')
        ax.set_ylabel('出现频率 (%)')
        ax.set_title(f'红球冷热走势 (最近{recent_periods}期, Top{top_n})')
        ax.legend(loc='upper left', ncol=5, fontsize=8)
        ax.grid(True, alpha=0.3)
        
        # 设置x轴标签
        step = max(1, len(periods) // 10)
        ax.set_xticks(range(0, len(periods), step))
        ax.set_xticklabels([periods[i] for i in range(0, len(periods), step)], rotation=45)
        
        return self._save_chart('hot_cold_trend.png')
    
    # ========================================================================
    # 2. 遗漏值走势图
    # ========================================================================
    def generate_missing_trend(self, recent_periods=30):
        """生成遗漏值走势图"""
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        recent = self.records[-recent_periods:]
        
        # 计算每个号码的遗漏值
        missing_data = {i: [] for i in range(1, 34)}
        last_seen = {i: -1 for i in range(1, 34)}
        
        for idx, record in enumerate(recent):
            for num in range(1, 34):
                if num in record['red_balls']:
                    last_seen[num] = idx
                    missing_data[num].append(0)
                else:
                    missing_data[num].append(idx - last_seen[num] if last_seen[num] >= 0 else idx)
        
        # 绘制热力图
        fig, ax = plt.subplots(figsize=(14, 8))
        
        # 准备数据矩阵
        matrix = []
        labels = []
        for num in range(1, 34):
            matrix.append(missing_data[num])
            labels.append(f'{num:02d}')
        
        im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
        
        ax.set_yticks(range(33))
        ax.set_yticklabels(labels)
        ax.set_xlabel('期数')
        ax.set_ylabel('号码')
        ax.set_title(f'红球遗漏值热力图 (最近{recent_periods}期)')
        
        # 添加颜色条
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('遗漏期数')
        
        # 设置x轴标签
        periods = [r['period'] for r in recent]
        step = max(1, len(periods) // 10)
        ax.set_xticks(range(0, len(periods), step))
        ax.set_xticklabels([periods[i] for i in range(0, len(periods), step)], rotation=45)
        
        return self._save_chart('missing_heatmap.png')
    
    # ========================================================================
    # 3. 和值分布图
    # ========================================================================
    def generate_sum_distribution(self, recent_periods=100):
        """生成和值分布图"""
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        recent = self.records[-recent_periods:]
        sums = [sum(r['red_balls']) for r in recent]
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
        
        # 和值走势
        ax1.plot(range(len(sums)), sums, 'b-', linewidth=1)
        ax1.axhline(y=sum(sums)/len(sums), color='r', linestyle='--', label=f'平均值: {sum(sums)/len(sums):.1f}')
        ax1.set_xlabel('期数')
        ax1.set_ylabel('和值')
        ax1.set_title(f'红球和值走势 (最近{recent_periods}期)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 和值分布直方图
        ax2.hist(sums, bins=20, edgecolor='black', alpha=0.7)
        ax2.axvline(x=sum(sums)/len(sums), color='r', linestyle='--', label='平均值')
        ax2.set_xlabel('和值')
        ax2.set_ylabel('频数')
        ax2.set_title('和值分布')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        return self._save_chart('sum_distribution.png')
    
    # ========================================================================
    # 4. 区间分布图
    # ========================================================================
    def generate_zone_distribution(self, recent_periods=50):
        """生成区间分布图"""
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        recent = self.records[-recent_periods:]
        
        zone1_counts = []  # 1-11
        zone2_counts = []  # 12-22
        zone3_counts = []  # 23-33
        
        for record in recent:
            balls = record['red_balls']
            zone1_counts.append(sum(1 for b in balls if 1 <= b <= 11))
            zone2_counts.append(sum(1 for b in balls if 12 <= b <= 22))
            zone3_counts.append(sum(1 for b in balls if 23 <= b <= 33))
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        x = range(len(recent))
        width = 0.25
        
        ax.bar([i - width for i in x], zone1_counts, width, label='前区(1-11)', alpha=0.8)
        ax.bar(x, zone2_counts, width, label='中区(12-22)', alpha=0.8)
        ax.bar([i + width for i in x], zone3_counts, width, label='后区(23-33)', alpha=0.8)
        
        ax.set_xlabel('期数')
        ax.set_ylabel('号码个数')
        ax.set_title(f'三区分布 (最近{recent_periods}期)')
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        # 设置x轴标签
        periods = [r['period'] for r in recent]
        step = max(1, len(periods) // 10)
        ax.set_xticks(range(0, len(periods), step))
        ax.set_xticklabels([periods[i] for i in range(0, len(periods), step)], rotation=45)
        
        return self._save_chart('zone_distribution.png')
    
    # ========================================================================
    # 5. 奇偶比/大小比趋势图
    # ========================================================================
    def generate_ratio_trend(self, recent_periods=50):
        """生成奇偶比和大小比趋势图"""
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        recent = self.records[-recent_periods:]
        
        odd_ratios = []
        big_ratios = []
        periods = []
        
        for record in recent:
            balls = record['red_balls']
            odd_count = sum(1 for b in balls if b % 2 == 1)
            big_count = sum(1 for b in balls if b >= 17)
            
            odd_ratios.append(odd_count)
            big_ratios.append(big_count)
            periods.append(record['period'])
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
        
        # 奇偶比
        ax1.plot(range(len(odd_ratios)), odd_ratios, 'bo-', linewidth=1, markersize=3)
        ax1.axhline(y=3, color='r', linestyle='--', label='平衡线(3:3)')
        ax1.set_xlabel('期数')
        ax1.set_ylabel('奇数个数')
        ax1.set_title('奇偶比趋势')
        ax1.set_ylim(0, 6)
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 大小比
        ax2.plot(range(len(big_ratios)), big_ratios, 'go-', linewidth=1, markersize=3)
        ax2.axhline(y=3, color='r', linestyle='--', label='平衡线(3:3)')
        ax2.set_xlabel('期数')
        ax2.set_ylabel('大数个数(≥17)')
        ax2.set_title('大小比趋势')
        ax2.set_ylim(0, 6)
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # 设置x轴标签
        step = max(1, len(periods) // 10)
        for ax in [ax1, ax2]:
            ax.set_xticks(range(0, len(periods), step))
            ax.set_xticklabels([periods[i] for i in range(0, len(periods), step)], rotation=45)
        
        plt.tight_layout()
        return self._save_chart('ratio_trend.png')
    
    # ========================================================================
    # 6. 蓝球走势+遗漏图
    # ========================================================================
    def generate_blue_ball_trend(self, recent_periods=50):
        """生成蓝球走势图"""
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        recent = self.records[-recent_periods:]
        
        blue_balls = [r['blue_ball'] for r in recent]
        periods = [r['period'] for r in recent]
        
        # 计算蓝球遗漏
        blue_missing = {i: 0 for i in range(1, 17)}
        last_seen = {i: -1 for i in range(1, 17)}
        
        missing_trend = {i: [] for i in range(1, 17)}
        
        for idx, record in enumerate(recent):
            blue = record['blue_ball']
            for num in range(1, 17):
                if num == blue:
                    last_seen[num] = idx
                    missing_trend[num].append(0)
                else:
                    miss = idx - last_seen[num] if last_seen[num] >= 0 else idx
                    missing_trend[num].append(miss)
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
        
        # 蓝球走势
        ax1.plot(range(len(blue_balls)), blue_balls, 'bo-', linewidth=1, markersize=4)
        ax1.set_xlabel('期数')
        ax1.set_ylabel('蓝球号码')
        ax1.set_title('蓝球走势')
        ax1.set_ylim(0, 17)
        ax1.grid(True, alpha=0.3)
        
        # 蓝球遗漏热力图
        matrix = [missing_trend[i] for i in range(1, 17)]
        im = ax2.imshow(matrix, cmap='YlOrRd', aspect='auto')
        ax2.set_yticks(range(16))
        ax2.set_yticklabels([f'{i:02d}' for i in range(1, 17)])
        ax2.set_xlabel('期数')
        ax2.set_ylabel('蓝球号码')
        ax2.set_title('蓝球遗漏热力图')
        
        cbar = plt.colorbar(im, ax=ax2)
        cbar.set_label('遗漏期数')
        
        # 设置x轴标签
        step = max(1, len(periods) // 10)
        for ax in [ax1, ax2]:
            ax.set_xticks(range(0, len(periods), step))
            ax.set_xticklabels([periods[i] for i in range(0, len(periods), step)], rotation=45)
        
        plt.tight_layout()
        return self._save_chart('blue_ball_trend.png')
    
    # ========================================================================
    # 生成所有图表
    # ========================================================================
    def generate_all_charts(self):
        """生成所有走势图"""
        if not MATPLOTLIB_AVAILABLE:
            print("❌ matplotlib未安装，无法生成图表")
            return []
        
        print("=" * 60)
        print("📊 生成可视化走势图")
        print("=" * 60)
        
        generated = []
        
        print("\n1. 红球冷热走势图...")
        chart = self.generate_hot_cold_trend(top_n=10, recent_periods=50)
        if chart:
            generated.append(chart)
        
        print("\n2. 遗漏值热力图...")
        chart = self.generate_missing_trend(recent_periods=30)
        if chart:
            generated.append(chart)
        
        print("\n3. 和值分布图...")
        chart = self.generate_sum_distribution(recent_periods=100)
        if chart:
            generated.append(chart)
        
        print("\n4. 区间分布图...")
        chart = self.generate_zone_distribution(recent_periods=50)
        if chart:
            generated.append(chart)
        
        print("\n5. 奇偶比/大小比趋势图...")
        chart = self.generate_ratio_trend(recent_periods=50)
        if chart:
            generated.append(chart)
        
        print("\n6. 蓝球走势+遗漏图...")
        chart = self.generate_blue_ball_trend(recent_periods=50)
        if chart:
            generated.append(chart)
        
        print("\n" + "=" * 60)
        print(f"✅ 共生成 {len(generated)} 张图表")
        print(f"📁 保存位置: {self.output_dir}/")
        print("=" * 60)
        
        return generated


def main():
    """主函数"""
    print("=" * 60)
    print("📊 双色球可视化分析工具")
    print("=" * 60)
    
    # 加载数据
    try:
        with open('lottery_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        records = data.get('records', [])
        print(f"\n📁 加载了 {len(records)} 期数据")
    except Exception as e:
        print(f"❌ 加载数据失败: {e}")
        return
    
    if not records:
        print("❌ 没有数据")
        return
    
    # 创建分析器并生成图表
    analyzer = VisualAnalyzer(records, output_dir='charts')
    analyzer.generate_all_charts()
    
    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
