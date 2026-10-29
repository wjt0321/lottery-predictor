#!/usr/bin/env python3
"""
最近10期命中率分析。
- 输入: lottery_data.json(开奖) + prediction_archive/2026095..2026104.txt(预测)
- 输出: 每期最佳命中 + 整体命中率 + 与基线对比
"""
import os, re, json
from pathlib import Path

DATA = "lottery_data.json"
ARCHIVE = Path("prediction_archive")

# 1. 加载开奖数据
with open(DATA, encoding="utf-8") as f:
    raw = json.load(f)
records = sorted(raw["records"], key=lambda r: r["period"])
by_period = {r["period"]: r for r in records}

# 2. 最近10期(已开奖,且有对应预测文件)
periods = [p for p in sorted(by_period.keys(), reverse=True)
           if (ARCHIVE / f"{p}.txt").exists()][:10]
periods = sorted(periods)  # 正序

print("=" * 70)
print(f"最近 {len(periods)} 期命中率分析(每期5注)")
print("=" * 70)

def parse_pred_file(p):
    """从归档txt里提取5注 (red, blue)。
    真实格式: ticket1=04 05 06 16 18 24+10|...
    """
    text = (ARCHIVE / f"{p}.txt").read_text(encoding="utf-8", errors="replace")
    bets = []
    # ticket1..ticket5: 6红 + 蓝
    for m in re.finditer(r"^ticket([1-5])=([\d\s]+)\+(\d+)", text, re.MULTILINE):
        red = sorted(int(x) for x in m.group(2).split())
        blue = int(m.group(3))
        if len(red) == 6:
            bets.append((red, blue))
    return bets

results = []
all_red_hits, all_blue_hits = [], []
max_red_per_period = []
five_hit_periods = []  # 5红中的期
six_hit_periods = []   # 6红中的期
blue_hit_periods = []
total_bets = 0
total_red_hits_sum = 0  # 5注 ×6红 = 30球 位
total_blue_hits_sum = 0

print(f"{'期号':<10}{'开奖日':<12}{'最佳红':<8}{'最佳蓝':<8}{'注数红分布':<20}")
print("-" * 70)

for p in periods:
    rec = by_period[p]
    actual_red = set(rec["red_balls"])
    actual_blue = rec["blue_ball"]
    bets = parse_pred_file(p)
    if not bets:
        print(f"{p:<10} NO BETS PARSED")
        continue

    per_bet = []
    best_red = 0
    best_blue = 0
    red_dist = [0]*7  # 0..6
    for red, blue in bets:
        rh = len(actual_red & set(red))
        bh = 1 if blue == actual_blue else 0
        per_bet.append((rh, bh))
        best_red = max(best_red, rh)
        best_blue = max(best_blue, bh)
        red_dist[rh] += 1
        total_bets += 1
        total_red_hits_sum += rh
        total_blue_hits_sum += bh

    max_red_per_period.append(best_red)
    all_red_hits.extend([x[0] for x in per_bet])
    all_blue_hits.extend([x[1] for x in per_bet])
    if best_red == 5:
        five_hit_periods.append(p)
    if best_red == 6:
        six_hit_periods.append(p)
    if best_blue == 1:
        blue_hit_periods.append(p)
    results.append({
        "period": p, "date": rec["date"], "best_red": best_red,
        "best_blue": best_blue, "red_dist": red_dist,
        "actual": (sorted(actual_red), actual_blue),
    })
    dist_str = ",".join(f"{i}:{red_dist[i]}" for i in range(7))
    print(f"{p:<10}{rec['date']:<12}{best_red:<8}{best_blue:<8}{dist_str}")

print("-" * 70)
print()
print("【整体指标】")
print(f"  总注数: {total_bets} (10 期 × 5 注)")
print(f"  5+红球命中期: {len(five_hit_periods)} / 10 → {', '.join(five_hit_periods) if five_hit_periods else '无'}")
print(f"  6红球命中期: {len(six_hit_periods)} / 10 → {', '.join(six_hit_periods) if six_hit_periods else '无'}")
print(f"  蓝球命中期: {len(blue_hit_periods)} / 10 → {', '.join(blue_hit_periods) if blue_hit_periods else '无'}")
print()
print(f"  每注平均红球命中: {total_red_hits_sum/total_bets:.3f} (纯随机期望 ≈ 1.0)")
print(f"  每注蓝球命中率: {total_blue_hits_sum/total_bets*100:.2f}% (纯随机期望 ≈ 6.67%)")
print()
print("  最佳命中分布:")
from collections import Counter
c = Counter(max_red_per_period)
for k in sorted(c.keys()):
    print(f"    最佳 {k} 红: {c[k]} 期")
print()

# 3. 基线对比:随机选号 vs 当前模型
# 基线:每注6红 = 6/33 = 0.182 期望/位,6位 = 1.091
# 蓝球:1/16 = 6.25%
# 蒙特卡洛10000次,每注独立抽样 vs 同一期开奖
import random
random.seed(42)
N_TRIALS = 10000
reds_all = list(range(1, 34))
blues_all = list(range(1, 17))
last_rec = by_period[periods[-1]]
actual_r = set(last_rec["red_balls"]); actual_b = last_rec["blue_ball"]

# 单注基线
single_red_hits, single_blue_hits = [], []
for _ in range(N_TRIALS):
    r = random.sample(reds_all, 6)
    b = random.choice(blues_all)
    single_red_hits.append(len(actual_r & set(r)))
    single_blue_hits.append(1 if b == actual_b else 0)

# 5注最佳命中基线(每组抽5注,取最佳)
best_red_5, best_blue_5, baseline_5red, baseline_blue_hit = [], [], 0, 0
for _ in range(N_TRIALS):
    best_r = 0; best_b = 0
    for _ in range(5):
        r = random.sample(reds_all, 6)
        b = random.choice(blues_all)
        best_r = max(best_r, len(actual_r & set(r)))
        best_b = max(best_b, 1 if b == actual_b else 0)
    best_red_5.append(best_r); best_blue_5.append(best_b)
    if best_r >= 5: baseline_5red += 1
    if best_b == 1: baseline_blue_hit += 1

print("【基线对比(蒙特卡洛 10000 次 vs 最近期开奖 2026104)】")
print(f"  单注随机:每注红球命中均值 = {sum(single_red_hits)/N_TRIALS:.3f}")
print(f"  单注随机:每注蓝球命中率 = {sum(single_blue_hits)/N_TRIALS*100:.2f}%")
print(f"  5注随机:最佳≥5红的概率 = {baseline_5red/N_TRIALS*100:.3f}%")
print(f"  5注随机:最佳蓝球命中概率 = {baseline_blue_hit/N_TRIALS*100:.2f}%")
print(f"  5注随机:最佳红球均值 = {sum(best_red_5)/N_TRIALS:.3f}")
print()

# 4. 折算:如果把"5注买一次"当一次实验,10期里实际命中情况
print("【实战对照(10期累计)】")
print(f"  模型实际最佳命中分布: {dict(counter := Counter(max_red_per_period))}")
print(f"  模型5红以上: {len(five_hit_periods)+len(six_hit_periods)}/10")
print(f"  模型蓝球命中: {len(blue_hit_periods)}/10")
print()
print("=" * 70)
print("结论:")
hit_ratio = total_red_hits_sum/total_bets
random_ratio = 6/33  # 1.091... 但实测用蒙特卡洛
print(f"  ① 红球每注命中 {hit_ratio:.3f} vs 随机基线 {sum(single_red_hits)/N_TRIALS:.3f} → 提升 {(hit_ratio/(sum(single_red_hits)/N_TRIALS)-1)*100:+.1f}%")
bh_ratio = total_blue_hits_sum/total_bets
print(f"  ② 蓝球每注命中 {bh_ratio*100:.2f}% vs 随机基线 {sum(single_blue_hits)/N_TRIALS*100:.2f}% → 提升 {(bh_ratio/(sum(single_blue_hits)/N_TRIALS)-1)*100:+.1f}%")
print(f"  ③ 5注最佳命中 ≥5红 期数: {len(five_hit_periods)+len(six_hit_periods)}/10 (随机10000次实证:每5注约 {baseline_5red/N_TRIALS*100:.2f}%)")
print(f"  ④ 蓝球命中转化率(5注最佳): {len(blue_hit_periods)/10*100:.1f}% (随机10000次实证: {baseline_blue_hit/N_TRIALS*100:.2f}%)")
print(f"  ⑤ 5注最佳红球均值: {sum(max_red_per_period)/len(max_red_per_period):.2f} (随机10000次: {sum(best_red_5)/N_TRIALS:.2f})")