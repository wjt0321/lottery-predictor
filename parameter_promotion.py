#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence-gated review for calibration-driven parameter promotion.

This module never activates a parameter patch.  It can write an auditable
review decision and, only when every gate passes, a candidate patch for later
human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from typing import Dict, Iterable, List, Optional, Tuple

CALIBRATION_SCHEMA = "threshold-calibration/v1"
STABILITY_SCHEMA = "stability-report/v2"
THRESHOLD_KEYS = ("one_score_threshold", "two_score_threshold", "min_score_gap")


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_thresholds(value: object) -> Optional[Dict[str, float]]:
    if not isinstance(value, dict):
        return None
    try:
        result = {key: round(float(value[key]), 6) for key in THRESHOLD_KEYS}
    except (KeyError, TypeError, ValueError):
        return None
    if result["two_score_threshold"] < result["one_score_threshold"]:
        return None
    if any(number < 0.0 for number in result.values()):
        return None
    return result


def _gate(name: str, passed: bool, observed: object, required: object) -> Dict[str, object]:
    return {
        "name": name,
        "passed": bool(passed),
        "observed": observed,
        "required": required,
    }


def _selection_leader(calibration_report: Dict[str, object]) -> Tuple[Optional[Dict[str, float]], int, float, bool]:
    aggregate = calibration_report.get("aggregate", {})
    frequency = aggregate.get("selection_frequency", []) if isinstance(aggregate, dict) else []
    rows = []
    for row in frequency if isinstance(frequency, list) else []:
        if not isinstance(row, dict):
            continue
        thresholds = _normalize_thresholds(row.get("thresholds"))
        if thresholds is None:
            continue
        try:
            count = max(0, int(row.get("count", 0)))
            ratio = float(row.get("ratio", 0.0))
        except (TypeError, ValueError):
            continue
        rows.append((count, ratio, thresholds))
    rows.sort(key=lambda item: (-item[0], -item[1], json.dumps(item[2], sort_keys=True)))
    if not rows:
        return None, 0, 0.0, False
    top_count, top_ratio, top_thresholds = rows[0]
    second_count = rows[1][0] if len(rows) > 1 else -1
    return top_thresholds, top_count, round(top_ratio, 6), top_count > second_count


def _default_thresholds(calibration_report: Dict[str, object]) -> Optional[Dict[str, float]]:
    folds = calibration_report.get("folds", [])
    candidates: List[Dict[str, float]] = []
    for fold in folds if isinstance(folds, list) else []:
        if not isinstance(fold, dict):
            continue
        for row in fold.get("candidate_ranking", []) if isinstance(fold.get("candidate_ranking", []), list) else []:
            if not isinstance(row, dict):
                continue
            try:
                distance = abs(float(row.get("distance_from_default", 1.0)))
            except (TypeError, ValueError):
                continue
            if distance <= 1e-12:
                thresholds = _normalize_thresholds(row.get("thresholds"))
                if thresholds is not None:
                    candidates.append(thresholds)
    if not candidates:
        return None
    first = candidates[0]
    if all(candidate == first for candidate in candidates):
        return first
    return None


def _candidate_patch(thresholds: Dict[str, float]) -> Dict[str, object]:
    return {
        "fusion_params": {
            "anti_ticket_dynamic_one_score_threshold": thresholds["one_score_threshold"],
            "anti_ticket_dynamic_two_score_threshold": thresholds["two_score_threshold"],
            "anti_ticket_dynamic_min_score_gap": thresholds["min_score_gap"],
        }
    }


def review_parameter_promotion(
    calibration_report: Dict[str, object],
    stability_report: Optional[Dict[str, object]] = None,
    *,
    min_folds: int = 3,
    min_validation_samples: int = 12,
    min_concentration: float = 2.0 / 3.0,
    min_positive_fold_ratio: float = 2.0 / 3.0,
    min_validation_mean: float = 0.0,
    min_validation_ci_low: float = 0.0,
    min_stability_runs: int = 12,
    min_stability_positive_ratio: float = 0.75,
    min_stability_ci_low: float = 0.0,
) -> Dict[str, object]:
    """Return an auditable candidate-promotion decision.

    Every gate must pass before ``candidate_patch`` is included.  A malformed
    report safely degrades to ``hold`` rather than raising or writing a patch.
    """
    calibration_report = calibration_report if isinstance(calibration_report, dict) else {}
    gates: List[Dict[str, object]] = []
    schema = str(calibration_report.get("report_schema_version", ""))
    gates.append(_gate("calibration_schema", schema == CALIBRATION_SCHEMA, schema or "missing", CALIBRATION_SCHEMA))

    folds = calibration_report.get("folds", [])
    folds = folds if isinstance(folds, list) else []
    gates.append(_gate("minimum_folds", len(folds) >= int(min_folds), len(folds), int(min_folds)))

    validation_counts: List[int] = []
    fold_deltas: List[float] = []
    for fold in folds:
        if not isinstance(fold, dict):
            validation_counts.append(0)
            fold_deltas.append(0.0)
            continue
        try:
            validation_counts.append(int(fold.get("validation_samples", 0)))
        except (TypeError, ValueError):
            validation_counts.append(0)
        try:
            fold_deltas.append(float(fold.get("selected_vs_default_delta", 0.0)))
        except (TypeError, ValueError):
            fold_deltas.append(0.0)
    minimum_observed = min(validation_counts) if validation_counts else 0
    gates.append(_gate(
        "minimum_validation_samples",
        bool(validation_counts) and minimum_observed >= int(min_validation_samples),
        minimum_observed,
        int(min_validation_samples),
    ))

    candidate, leader_count, concentration, unique_leader = _selection_leader(calibration_report)
    gates.append(_gate("unique_threshold_leader", unique_leader, leader_count, "strictly greater than runner-up"))
    gates.append(_gate("threshold_concentration", concentration >= float(min_concentration), concentration, float(min_concentration)))

    default_thresholds = _default_thresholds(calibration_report)
    candidate_differs = candidate is not None and default_thresholds is not None and candidate != default_thresholds
    gates.append(_gate(
        "candidate_differs_from_default",
        candidate_differs,
        {"candidate": candidate, "default": default_thresholds},
        "different normalized threshold sets",
    ))

    aggregate = calibration_report.get("aggregate", {})
    delta_stats = aggregate.get("selected_vs_default_delta", {}) if isinstance(aggregate, dict) else {}
    delta_stats = delta_stats if isinstance(delta_stats, dict) else {}
    try:
        validation_mean = float(delta_stats.get("mean", 0.0))
    except (TypeError, ValueError):
        validation_mean = 0.0
    try:
        validation_ci_low = float(delta_stats.get("ci95_low", 0.0))
    except (TypeError, ValueError):
        validation_ci_low = 0.0
    gates.append(_gate("positive_validation_mean", validation_mean > float(min_validation_mean), validation_mean, f"> {float(min_validation_mean)}"))
    gates.append(_gate("validation_ci_nonnegative", validation_ci_low >= float(min_validation_ci_low), validation_ci_low, float(min_validation_ci_low)))

    positive_count = sum(1 for delta in fold_deltas if delta > 1e-12)
    positive_ratio = positive_count / len(fold_deltas) if fold_deltas else 0.0
    gates.append(_gate("positive_fold_ratio", positive_ratio >= float(min_positive_fold_ratio), round(positive_ratio, 6), float(min_positive_fold_ratio)))

    if stability_report is not None:
        stability_report = stability_report if isinstance(stability_report, dict) else {}
        stability_schema = str(stability_report.get("report_schema_version", ""))
        gates.append(_gate("stability_schema", stability_schema == STABILITY_SCHEMA, stability_schema or "missing", STABILITY_SCHEMA))
        stability_aggregate = stability_report.get("aggregate", {})
        paired = stability_aggregate.get("paired", {}) if isinstance(stability_aggregate, dict) else {}
        paired = paired if isinstance(paired, dict) else {}
        objective_delta = paired.get("objective_delta", {})
        objective_delta = objective_delta if isinstance(objective_delta, dict) else {}
        try:
            stability_samples = int(objective_delta.get("samples", 0))
        except (TypeError, ValueError):
            stability_samples = 0
        try:
            stability_positive_ratio = float(paired.get("dynamic_positive_ratio", 0.0))
        except (TypeError, ValueError):
            stability_positive_ratio = 0.0
        try:
            stability_ci_low = float(objective_delta.get("ci95_low", 0.0))
        except (TypeError, ValueError):
            stability_ci_low = 0.0
        gates.extend([
            _gate("stability_minimum_runs", stability_samples >= int(min_stability_runs), stability_samples, int(min_stability_runs)),
            _gate("stability_positive_ratio", stability_positive_ratio >= float(min_stability_positive_ratio), stability_positive_ratio, float(min_stability_positive_ratio)),
            _gate("stability_ci_nonnegative", stability_ci_low >= float(min_stability_ci_low), stability_ci_low, float(min_stability_ci_low)),
        ])

    eligible = bool(gates) and all(gate["passed"] for gate in gates)
    result: Dict[str, object] = {
        "review_schema_version": "parameter-promotion-review/v1",
        "decision": "eligible" if eligible else "hold",
        "eligible": eligible,
        "candidate_thresholds": candidate,
        "default_thresholds": default_thresholds,
        "observed": {
            "fold_count": len(folds),
            "minimum_validation_samples": minimum_observed,
            "threshold_leader_count": leader_count,
            "threshold_concentration": concentration,
            "selected_vs_default_mean": round(validation_mean, 6),
            "selected_vs_default_ci95_low": round(validation_ci_low, 6),
            "positive_fold_ratio": round(positive_ratio, 6),
        },
        "gates": gates,
        "reasons": [gate["name"] for gate in gates if not gate["passed"]],
        "source_fingerprints": {
            "calibration_sha256": _canonical_hash(calibration_report),
            "stability_sha256": _canonical_hash(stability_report) if stability_report is not None else "not-supplied",
        },
        "activation": {
            "automatic": False,
            "latest_patch_overwrite": False,
            "requires_human_review": True,
        },
    }
    if eligible and candidate is not None:
        result["candidate_patch"] = _candidate_patch(candidate)
    return result


def _load_json(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _atomic_write_json(path: str, value: Dict[str, object]) -> str:
    target = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(target) or os.getcwd()
    os.makedirs(parent, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(prefix=f".{os.path.basename(target)}.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, target)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review rolling-calibration evidence before promoting dynamic-offset parameters")
    parser.add_argument("--calibration-report", required=True, help="threshold-calibration/v1 JSON report")
    parser.add_argument("--stability-report", default=None, help="optional stability-report/v2 JSON report")
    parser.add_argument("--output", default=None, help="write the complete audit decision JSON")
    parser.add_argument("--candidate-patch-output", default=None, help="write a candidate patch only when all gates pass")
    parser.add_argument("--min-folds", type=int, default=3)
    parser.add_argument("--min-validation-samples", type=int, default=12)
    parser.add_argument("--min-concentration", type=float, default=2.0 / 3.0)
    parser.add_argument("--min-positive-fold-ratio", type=float, default=2.0 / 3.0)
    parser.add_argument("--min-validation-mean", type=float, default=0.0)
    parser.add_argument("--min-validation-ci-low", type=float, default=0.0)
    parser.add_argument("--min-stability-runs", type=int, default=12)
    parser.add_argument("--min-stability-positive-ratio", type=float, default=0.75)
    parser.add_argument("--min-stability-ci-low", type=float, default=0.0)
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    calibration = _load_json(args.calibration_report)
    stability = _load_json(args.stability_report) if args.stability_report else None
    decision = review_parameter_promotion(
        calibration,
        stability,
        min_folds=args.min_folds,
        min_validation_samples=args.min_validation_samples,
        min_concentration=args.min_concentration,
        min_positive_fold_ratio=args.min_positive_fold_ratio,
        min_validation_mean=args.min_validation_mean,
        min_validation_ci_low=args.min_validation_ci_low,
        min_stability_runs=args.min_stability_runs,
        min_stability_positive_ratio=args.min_stability_positive_ratio,
        min_stability_ci_low=args.min_stability_ci_low,
    )
    print(f"parameter promotion decision: {decision['decision']}")
    if decision["reasons"]:
        print("failed gates: " + ", ".join(decision["reasons"]))
    if args.output:
        print(f"audit decision: {_atomic_write_json(args.output, decision)}")
    if args.candidate_patch_output and decision.get("candidate_patch"):
        if os.path.basename(os.path.normcase(args.candidate_patch_output)) == "param_patch.latest.json":
            raise ValueError("candidate review refuses to overwrite param_patch.latest.json")
        print(f"candidate patch: {_atomic_write_json(args.candidate_patch_output, decision['candidate_patch'])}")
    elif args.candidate_patch_output:
        print("candidate patch: not written (decision is hold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
