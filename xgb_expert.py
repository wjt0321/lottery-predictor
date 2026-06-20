#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XGBoost 特征分析与概率评分模块。

对每期历史数据构建 33 个红球的特征向量，用 walk-forward 时间序列
交叉验证训练 XGBoost 二分类器（"该球下期是否出现"），输出概率分数
替代/增强现有统计专家的核心池评分。

训练策略：对每期历史（作为预测点），用该期之前所有数据训练模型，
然后用训练好的模型预测该期的概率分数。回测时重复此过程。

零数据泄露：训练数据严格截止到预测期之前。
"""

import math
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════
# 特征工程
# ══════════════════════════════════════════════════════════════════════════


def _ball_features(records: List[Dict], ball: int, predict_idx: int) -> Dict[str, float]:
    """为单个红球构建特征向量。

    Args:
        records: 完整历史数据（按时间倒序，records[0]=最新期）
        ball: 红球号码 (1-33)
        predict_idx: 预测点在 records 中的索引（records[predict_idx] 是我们要预测的那期）
                     训练时 predict_idx=0（最新期），特征只用 predict_idx 之前的数据

    Returns:
        特征字典
    """
    # 只用 predict_idx 之前的数据（之后的都是"未来"）
    history = records[predict_idx + 1:] if predict_idx + 1 < len(records) else []

    features = {"ball": float(ball)}

    if not history:
        # 无历史数据，返回默认特征
        for k in _default_feature_names():
            if k not in features:
                features[k] = 0.0
        return features

    total = len(history)

    # ── 频率特征 ──
    for window in [5, 10, 20, 30, 50, 100]:
        w = min(window, total)
        count = sum(1 for r in history[:w] if ball in r.get("red_balls", []))
        features[f"freq_{window}"] = float(count)
        features[f"freq_{window}_rate"] = count / w

    # ── 遗漏特征 ──
    last_seen = -1
    for idx, r in enumerate(history):
        if ball in r.get("red_balls", []):
            last_seen = idx
            break
    features["missing"] = float(last_seen if last_seen >= 0 else total)
    features["missing_log"] = math.log(1 + features["missing"])

    # ── 冷热标记 ──
    features["is_hot"] = 1.0 if features.get("freq_10", 0) >= 2 else 0.0
    features["is_cold"] = 1.0 if features.get("freq_50", 0) <= 3 else 0.0
    features["is_missing_extreme"] = 1.0 if features["missing"] >= 20 else 0.0

    # ── 球属性 ──
    features["is_odd"] = 1.0 if ball % 2 == 1 else 0.0
    if ball <= 11:
        features["zone"] = 1.0
    elif ball <= 22:
        features["zone"] = 2.0
    else:
        features["zone"] = 3.0
    features["is_small"] = 1.0 if ball <= 16 else 0.0

    # ── 近期连出/间隔 ──
    appearances = [i for i, r in enumerate(history) if ball in r.get("red_balls", [])]
    if len(appearances) >= 2:
        intervals = [appearances[i] - appearances[i + 1] for i in range(len(appearances) - 1)]
        features["avg_interval"] = sum(intervals) / len(intervals)
        features["interval_std"] = (
            math.sqrt(sum((x - features["avg_interval"]) ** 2 for x in intervals) / len(intervals))
            if len(intervals) > 1 else 0.0
        )
        features["last_interval"] = float(appearances[0] - appearances[1]) if len(appearances) >= 2 else 0.0
    else:
        features["avg_interval"] = float(total)
        features["interval_std"] = 0.0
        features["last_interval"] = float(total)

    # ── 共现特征：与近期热球的共现频率 ──
    recent_hot = set()
    hot_counter = Counter()
    for r in history[:10]:
        hot_counter.update(r.get("red_balls", []))
    for b, c in hot_counter.most_common(10):
        if c >= 2:
            recent_hot.add(b)
    cooc_count = 0
    for r in history[:30]:
        reds = set(r.get("red_balls", []))
        if ball in reds:
            cooc_count += len(reds & recent_hot)
    features["cooc_with_hot"] = float(cooc_count)

    # ── 全局趋势特征 ──
    if history:
        recent_10 = history[:10]
        avg_sum = sum(sum(r.get("red_balls", [])) for r in recent_10) / len(recent_10)
        avg_odd = sum(sum(1 for b in r.get("red_balls", []) if b % 2 == 1) for r in recent_10) / len(recent_10)
        features["recent_avg_sum"] = avg_sum
        features["recent_avg_odd"] = avg_odd
        features["ball_sum_contrib"] = ball / avg_sum if avg_sum > 0 else 0.0
        features["ball_odd_match"] = 1.0 - abs((1.0 if ball % 2 == 1 else 0.0) - avg_odd / 6.0)

    # ── 位置特征：该球在历史中的平均排序位置 ──
    pos_sum = 0.0
    pos_count = 0
    for r in history[:60]:
        reds = sorted(r.get("red_balls", []))
        if ball in reds:
            pos_sum += reds.index(ball) + 1
            pos_count += 1
    features["avg_position"] = pos_sum / pos_count if pos_count > 0 else 3.5

    return features


def _default_feature_names() -> List[str]:
    """返回所有特征名列表（供初始化默认值使用）。"""
    names = ["ball", "is_odd", "zone", "is_small"]
    for window in [5, 10, 20, 30, 50, 100]:
        names.append(f"freq_{window}")
        names.append(f"freq_{window}_rate")
    names.extend([
        "missing", "missing_log", "is_hot", "is_cold", "is_missing_extreme",
        "avg_interval", "interval_std", "last_interval",
        "cooc_with_hot", "recent_avg_sum", "recent_avg_odd",
        "ball_sum_contrib", "ball_odd_match", "avg_position",
    ])
    return names


def build_training_data(
    records: List[Dict],
    predict_indices: Optional[List[int]] = None,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray], List[str]]:
    """构建训练数据矩阵。

    Args:
        records: 历史数据（时间倒序）
        predict_indices: 要预测的期索引列表。如果为 None，用最近 min(50, len(records)-10) 期。

    Returns:
        X: 特征矩阵 (n_samples, n_features)
        y: 标签向量 (n_samples,) 1=该球出现, 0=未出现
        weights: 样本权重（近期样本权重更高）
        feature_names: 特征名列表
    """
    if not XGB_AVAILABLE or len(records) < 30:
        return None, None, None, []

    if predict_indices is None:
        n_pred = min(50, len(records) - 10)
        predict_indices = list(range(n_pred))

    feature_names = _default_feature_names()
    X_list = []
    y_list = []
    w_list = []

    for pred_idx in predict_indices:
        if pred_idx >= len(records) - 1:
            continue  # 没有足够历史数据
        # 该期实际开奖
        target = records[pred_idx]
        if "red_balls" not in target:
            continue
        target_reds = set(target["red_balls"])
        # 样本权重：越近期权重越高
        weight = math.exp(-pred_idx * 0.02)

        for ball in range(1, 34):
            feat = _ball_features(records, ball, pred_idx)
            row = [feat.get(name, 0.0) for name in feature_names]
            X_list.append(row)
            y_list.append(1.0 if ball in target_reds else 0.0)
            w_list.append(weight)

    if not X_list:
        return None, None, None, []

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    weights = np.array(w_list, dtype=np.float32)

    return X, y, weights, feature_names


# ══════════════════════════════════════════════════════════════════════════
# 模型训练与预测
# ══════════════════════════════════════════════════════════════════════════


def train_xgb_model(
    records: List[Dict],
    predict_idx: int = 0,
    num_boost_round: int = 100,
) -> Optional[object]:
    """训练 XGBoost 模型。

    用 predict_idx 之前的所有历史数据训练。

    Args:
        records: 历史数据（时间倒序）
        predict_idx: 预测期索引
        num_boost_round: 提升轮数

    Returns:
        训练好的 xgb.Booster，或 None（如果数据不足）
    """
    if not XGB_AVAILABLE or len(records) < 50:
        return None

    # 训练数据：predict_idx 之前的期
    train_indices = list(range(predict_idx + 1, min(predict_idx + 200, len(records))))
    if len(train_indices) < 30:
        train_indices = list(range(predict_idx + 1, len(records)))

    X, y, w, feature_names = build_training_data(records, train_indices)
    if X is None or len(X) < 100:
        return None

    # 处理类别不平衡：正例权重 = 负例数/正例数
    pos_count = int(y.sum())
    neg_count = len(y) - pos_count
    if pos_count > 0 and neg_count > 0:
        scale_pos_weight = neg_count / pos_count
    else:
        scale_pos_weight = 1.0

    dtrain = xgb.DMatrix(X, label=y, weight=w, feature_names=feature_names)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 5,
        "eta": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "gamma": 0.1,
        "lambda": 1.0,
        "scale_pos_weight": scale_pos_weight,
        "seed": 42,
        "verbosity": 0,
    }

    booster = xgb.train(params, dtrain, num_boost_round=num_boost_round)
    return booster


def predict_proba(
    booster: object,
    records: List[Dict],
    predict_idx: int = 0,
) -> Dict[int, float]:
    """用训练好的模型预测每个红球的出现概率。

    Returns:
        {ball: probability} 概率分数，可用于排名
    """
    if not XGB_AVAILABLE or booster is None:
        return {}

    feature_names = _default_feature_names()
    probs = {}

    for ball in range(1, 34):
        feat = _ball_features(records, ball, predict_idx)
        row = [feat.get(name, 0.0) for name in feature_names]
        X_pred = np.array([row], dtype=np.float32)
        dtest = xgb.DMatrix(X_pred, feature_names=feature_names)
        pred = booster.predict(dtest)
        probs[ball] = float(pred[0])

    return probs


def get_feature_importance(booster: object) -> Dict[str, float]:
    """获取特征重要性。"""
    if not XGB_AVAILABLE or booster is None:
        return {}
    scores = booster.get_score(importance_type="gain")
    return {k: float(v) for k, v in scores.items()}


# ══════════════════════════════════════════════════════════════════════════
# 集成接口（供 predict.py 调用）
# ══════════════════════════════════════════════════════════════════════════

# 模型缓存：避免重复训练
_MODEL_CACHE: Dict[int, object] = {}


def get_xgb_scores(
    records: List[Dict],
    predict_period: Optional[str] = None,
    force_retrain: bool = False,
) -> Dict[int, float]:
    """获取 XGBoost 预测的红球概率分数。

    自动缓存模型：相同 predict_period 复用缓存。

    Args:
        records: 历史数据（时间倒序）
        predict_period: 预测期号（用于缓存 key）
        force_retrain: 强制重新训练

    Returns:
        {ball: probability} — 概率越高越可能在下期出现
    """
    if not XGB_AVAILABLE or len(records) < 50:
        return {}

    cache_key = hash(predict_period or str(len(records)))
    if not force_retrain and cache_key in _MODEL_CACHE:
        booster = _MODEL_CACHE[cache_key]
        return predict_proba(booster, records)

    booster = train_xgb_model(records)
    if booster is not None:
        _MODEL_CACHE[cache_key] = booster
        # 清理旧缓存（只保留最近 3 个模型）
        if len(_MODEL_CACHE) > 3:
            oldest = min(_MODEL_CACHE.keys())
            del _MODEL_CACHE[oldest]

    return predict_proba(booster, records)


def clear_model_cache():
    """清除模型缓存。"""
    _MODEL_CACHE.clear()
