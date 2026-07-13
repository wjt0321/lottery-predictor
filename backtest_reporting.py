#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure helpers for stability reports, calibration grids, and report exports."""

import csv
import json
import math
import os
import random
from collections import defaultdict
from itertools import product
from typing import Dict, Iterable, List, Optional, Tuple

from project_config import GLOBAL_CONFIG

DEFAULT_RUNTIME_CONFIG = GLOBAL_CONFIG.to_runtime_config()

def _stable_int_seed(*parts: object) -> int:
    text = "|".join(str(part) for part in parts)
    acc = 0
    for char in text:
        acc = (acc * 131 + ord(char)) % (2 ** 32)
    return acc

def _deep_merge_dict(base: Dict[str, object], override: Dict[str, object]) -> Dict[str, object]:
    merged = json.loads(json.dumps(base))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged

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
