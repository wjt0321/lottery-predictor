#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
import logging
import os
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from agent_registry import VALID_AGENTS
from project_config import GLOBAL_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATA_FILE = GLOBAL_CONFIG.data_file


def _is_valid_agent(agent: object) -> bool:
    return str(agent) in VALID_AGENTS


def _iter_archive_files(archive_dir: str) -> List[str]:
    if not os.path.isdir(archive_dir):
        return []
    names = [name for name in os.listdir(archive_dir) if name.endswith(".txt")]
    names.sort(reverse=True)
    return [os.path.join(archive_dir, name) for name in names]


def _parse_archive_kv(file_path: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    with open(file_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def load_actual_records(data_file: str = DATA_FILE) -> List[Dict[str, object]]:
    if not data_file or not os.path.isfile(data_file):
        return []
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []
    records = payload.get("records", []) if isinstance(payload, dict) else []
    return records if isinstance(records, list) else []


def _actual_record_map(actual_records: Optional[List[Dict[str, object]]]) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    for record in actual_records or []:
        if not isinstance(record, dict):
            continue
        period = str(record.get("period", "")).strip()
        if period:
            result[period] = record
    return result


def _parse_ticket_numbers(ticket_text: str) -> tuple:
    ticket_part = str(ticket_text or "").split("|", 1)[0]
    red_part, blue_part = ("", "0")
    if "+" in ticket_part:
        red_part, blue_part = ticket_part.split("+", 1)
    red_numbers = [int(token) for token in red_part.split() if token.isdigit()]
    blue_text = "".join(ch for ch in blue_part if ch.isdigit())
    return sorted(red_numbers[:6]), int(blue_text or "0")


def _attach_actual_result(payload: Dict[str, object], ticket_text: str, actual_record: Optional[Dict[str, object]]) -> Dict[str, object]:
    if not actual_record:
        return payload
    if isinstance(payload.get("actual_result"), dict) and "hit_score" in payload["actual_result"]:
        return payload
    predicted_red, predicted_blue = _parse_ticket_numbers(ticket_text)
    actual_red = sorted(int(ball) for ball in actual_record.get("red_balls", []) or [])
    try:
        actual_blue = int(actual_record.get("blue_ball", 0))
    except Exception:
        actual_blue = 0
    red_hits = len(set(predicted_red) & set(actual_red))
    blue_hit = 1 if predicted_blue == actual_blue else 0
    enriched = dict(payload)
    enriched["actual_result"] = {
        "red_hits": red_hits,
        "blue_hit": blue_hit,
        "hit_score": red_hits + blue_hit * 1.5,
        "actual_red_balls": actual_red,
        "actual_blue_ball": actual_blue,
    }
    return enriched


def collect_explain_json_records(
    archive_dir: str,
    limit_files: Optional[int] = None,
    actual_records: Optional[List[Dict[str, object]]] = None,
) -> List[Dict[str, object]]:
    files = _iter_archive_files(archive_dir)
    if limit_files is not None:
        files = files[: max(0, int(limit_files))]
    actual_map = _actual_record_map(load_actual_records() if actual_records is None else actual_records)
    rows: List[Dict[str, object]] = []
    for file_path in files:
        values = _parse_archive_kv(file_path)
        period = values.get("period") or os.path.splitext(os.path.basename(file_path))[0]
        for key, raw in values.items():
            if not key.startswith("ticket") or not key.endswith("_explain_json"):
                continue
            ticket_part = key.split("_", 1)[0]
            ticket_index_text = ticket_part.replace("ticket", "")
            ticket_index = int(ticket_index_text) if ticket_index_text.isdigit() else 0
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            payload = _attach_actual_result(payload, values.get(ticket_part, ""), actual_map.get(str(period)))
            rows.append(
                {
                    "period": str(period),
                    "ticket_index": ticket_index,
                    "file_path": file_path,
                    "payload": payload,
                }
            )
    rows.sort(key=lambda r: (r["period"], r["ticket_index"]))
    return rows


def build_agent_ranking(records: List[Dict[str, object]]) -> List[Dict[str, object]]:
    score_by_agent = defaultdict(float)
    source_count = Counter()
    total_tickets = 0

    for row in records:
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        total_tickets += 1
        for agent in payload.get("sources", []) or []:
            if _is_valid_agent(agent):
                source_count[str(agent)] += 1
                score_by_agent.setdefault(str(agent), 0.0)
        actual_result = payload.get("actual_result", {}) or {}
        actual_red = set(actual_result.get("actual_red_balls", []) or []) if isinstance(actual_result, dict) else set()
        actual_blue = actual_result.get("actual_blue_ball") if isinstance(actual_result, dict) else None
        has_actual_balls = bool(actual_red) and actual_blue is not None
        for red in payload.get("red", []) or []:
            if not isinstance(red, dict):
                continue
            if has_actual_balls and int(red.get("ball", 0)) not in actual_red:
                continue
            contribs = red.get("agent_contributions", {}) or {}
            if isinstance(contribs, dict):
                for agent, val in contribs.items():
                    if not _is_valid_agent(agent):
                        continue
                    try:
                        score_by_agent[str(agent)] += float(val)
                    except Exception:
                        continue
        blue = payload.get("blue", {}) or {}
        if isinstance(blue, dict):
            if has_actual_balls and int(blue.get("ball", 0)) != int(actual_blue):
                continue
            contribs = blue.get("agent_contributions", {}) or {}
            if isinstance(contribs, dict):
                for agent, val in contribs.items():
                    if not _is_valid_agent(agent):
                        continue
                    try:
                        score_by_agent[str(agent)] += float(val)
                    except Exception:
                        continue

    ranking = []
    for agent, score in score_by_agent.items():
        ranking.append(
            {
                "agent": agent,
                "score": round(score, 6),
                "source_share": round(source_count.get(agent, 0) / total_tickets, 4) if total_tickets else 0.0,
                "source_count": int(source_count.get(agent, 0)),
            }
        )
    ranking.sort(key=lambda r: r["score"], reverse=True)
    return ranking


def build_matrix_row_ranking(records: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[tuple, Dict[str, float]] = {}
    for row in records:
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        matrix = payload.get("matrix", {})
        actual_result = payload.get("actual_result", {})
        if not isinstance(matrix, dict) or not isinstance(actual_result, dict):
            continue
        if not {"red_hits", "blue_hit", "hit_score"}.issubset(actual_result.keys()):
            continue
        row_id = matrix.get("row_id")
        matrix_type = str(matrix.get("type", "")).strip()
        if not row_id or not matrix_type:
            continue
        try:
            row_id = int(row_id)
            red_hits = float(actual_result.get("red_hits", 0.0))
            blue_hit = float(actual_result.get("blue_hit", 0.0))
            hit_score = float(actual_result.get("hit_score", 0.0))
        except Exception:
            continue
        key = (matrix_type, row_id)
        bucket = grouped.setdefault(
            key,
            {
                "matrix_type": matrix_type,
                "row_id": row_id,
                "samples": 0.0,
                "red_hits_total": 0.0,
                "blue_hits_total": 0.0,
                "hit_ge2_total": 0.0,
                "hit_ge3_total": 0.0,
                "score_total": 0.0,
            },
        )
        bucket["samples"] += 1.0
        bucket["red_hits_total"] += red_hits
        bucket["blue_hits_total"] += blue_hit
        bucket["hit_ge2_total"] += 1.0 if red_hits >= 2 else 0.0
        bucket["hit_ge3_total"] += 1.0 if red_hits >= 3 else 0.0
        bucket["score_total"] += hit_score

    ranking = []
    for bucket in grouped.values():
        samples = bucket["samples"] or 1.0
        ranking.append(
            {
                "matrix_type": bucket["matrix_type"],
                "row_id": int(bucket["row_id"]),
                "samples": int(samples),
                "red_hit_avg": round(bucket["red_hits_total"] / samples, 6),
                "blue_hit_rate": round(bucket["blue_hits_total"] / samples, 6),
                "hit_rate_ge2": round(bucket["hit_ge2_total"] / samples, 6),
                "hit_rate_ge3": round(bucket["hit_ge3_total"] / samples, 6),
                "avg_score": round(bucket["score_total"] / samples, 6),
            }
        )
    ranking.sort(key=lambda row: (-float(row["avg_score"]), -float(row["red_hit_avg"]), int(row["row_id"])))
    return ranking


def build_tuning_suggestions(ranking: List[Dict[str, object]], records: List[Dict[str, object]]) -> List[str]:
    lines: List[str] = []
    if not records:
        return ["未发现可解析的 ticketN_explain_json，先运行一次 team 模式生成新归档。"]

    top_agents = [row["agent"] for row in ranking[:3]]
    bottom_agents = [row["agent"] for row in ranking[-3:]] if len(ranking) >= 3 else []

    if top_agents:
        lines.append(f"建议提高权重倾斜：TOP3={','.join(top_agents)}（命中贡献累计更高；缺少真实结果时回退为 explain_json 贡献）。")
    if bottom_agents:
        lines.append(f"建议降低或观察：BOTTOM3={','.join(bottom_agents)}（命中贡献累计偏低；缺少真实结果时回退为 explain_json 贡献）。")

    replacement_total = 0
    ticket_total = 0
    for row in records:
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        ticket_total += 1
        repl = payload.get("diversity_replacements", []) or []
        if isinstance(repl, list) and repl:
            replacement_total += 1
    if ticket_total:
        ratio = replacement_total / ticket_total
        lines.append(f"多样性替换触发率：{ratio:.2%}（越高表示号码集中度越高，可考虑加强多样性惩罚或增加注间差异约束）。")

    lines.append("下一步可做自动调参：把 lead_model 权重/learning_rate/decay_gamma 作为变量，按 backtest_report 的 overall 指标网格搜索。")
    return lines


def _ranking_to_map(ranking: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    return {str(row.get("agent")): row for row in ranking}


def compute_dual_view_delta(
    recent_ranking: List[Dict[str, object]],
    all_time_ranking: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    recent_map = _ranking_to_map(recent_ranking)
    all_map = _ranking_to_map(all_time_ranking)
    agents = sorted(set(recent_map.keys()) | set(all_map.keys()))
    rows = []
    for agent in agents:
        recent_score = float(recent_map.get(agent, {}).get("score", 0.0))
        all_score = float(all_map.get(agent, {}).get("score", 0.0))
        delta = recent_score - all_score
        rows.append(
            {
                "agent": agent,
                "recent_score": round(recent_score, 6),
                "all_time_score": round(all_score, 6),
                "delta": round(delta, 6),
            }
        )
    rows.sort(key=lambda r: r["delta"], reverse=True)
    return rows


def build_weight_adjustments(
    recent_ranking: List[Dict[str, object]],
    all_time_ranking: List[Dict[str, object]],
    step: float = 0.02,
) -> List[Dict[str, object]]:
    delta_rows = compute_dual_view_delta(recent_ranking, all_time_ranking)
    if not delta_rows:
        return []
    peak = max(abs(float(r["delta"])) for r in delta_rows) or 1.0
    recommendations = []
    for row in delta_rows:
        norm = float(row["delta"]) / peak
        adjust = norm * step
        if adjust > step:
            adjust = step
        if adjust < -step:
            adjust = -step
        recommendations.append(
            {
                "agent": row["agent"],
                "delta": row["delta"],
                "weight_delta": round(adjust, 4),
            }
        )
    recommendations.sort(key=lambda r: r["weight_delta"], reverse=True)
    return recommendations


def _normalize_weight_map(weight_map: Dict[str, float]) -> Dict[str, float]:
    total = sum(max(float(v), 0.0) for v in weight_map.values())
    if total <= 0:
        if not weight_map:
            return {}
        uniform = 1.0 / len(weight_map)
        return {k: uniform for k in sorted(weight_map.keys())}
    return {k: max(float(v), 0.0) / total for k, v in weight_map.items()}


def build_weight_patch_payload(
    all_time_ranking: List[Dict[str, object]],
    weight_adjustments: List[Dict[str, object]],
) -> Dict[str, object]:
    agents = sorted(
        set(str(r.get("agent")) for r in all_time_ranking if r.get("agent") and _is_valid_agent(r.get("agent")))
        | set(str(r.get("agent")) for r in weight_adjustments if r.get("agent") and _is_valid_agent(r.get("agent")))
    )
    if not agents:
        return {"recommended_base_weights": {}, "weight_deltas": {}}
    score_map = {str(r["agent"]): float(r.get("score", 0.0)) for r in all_time_ranking if r.get("agent")}
    base_raw = {agent: score_map.get(agent, 0.0) for agent in agents}
    base = _normalize_weight_map(base_raw)
    if not base:
        base = {agent: 1.0 / len(agents) for agent in agents}
    delta_map = {str(r["agent"]): float(r.get("weight_delta", 0.0)) for r in weight_adjustments if r.get("agent")}
    patched_raw = {}
    for agent in agents:
        patched_raw[agent] = max(0.0001, float(base.get(agent, 0.0)) + float(delta_map.get(agent, 0.0)))
    patched = _normalize_weight_map(patched_raw)
    return {
        "version": 1,
        "agents": agents,
        "recommended_base_weights": {k: round(float(v), 6) for k, v in patched.items()},
        "weight_deltas": {k: round(float(delta_map.get(k, 0.0)), 6) for k in agents},
        "origin": "analyze_archive",
    }


def build_matrix_patch_payload(matrix_ranking: List[Dict[str, object]]) -> Dict[str, object]:
    if not matrix_ranking:
        return {
            "version": 1,
            "matrix_type": "",
            "row_weights": {},
            "row_scores": {},
            "origin": "analyze_archive",
        }
    matrix_type = str(matrix_ranking[0].get("matrix_type", "")).strip()
    score_map = {}
    for row in matrix_ranking:
        row_id = str(row.get("row_id"))
        score_map[row_id] = max(float(row.get("avg_score", 0.0)), 0.0001)
    row_weights = _normalize_weight_map(score_map)
    return {
        "version": 1,
        "matrix_type": matrix_type,
        "row_weights": {k: round(float(v), 6) for k, v in row_weights.items()},
        "row_scores": {str(row.get("row_id")): round(float(row.get("avg_score", 0.0)), 6) for row in matrix_ranking},
        "origin": "analyze_archive",
    }


def build_param_patch_payload(records: List[Dict[str, object]], matrix_ranking: List[Dict[str, object]]) -> Dict[str, object]:
    red_pool_sizes = []
    blue_pool_sizes = []
    diversity_trigger_count = 0
    matrix_type = ""
    for row in records:
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        core_pool = payload.get("core_pool", {})
        if isinstance(core_pool, dict):
            red_pool = core_pool.get("red_pool", []) or []
            blue_pool = core_pool.get("blue_pool", []) or []
            if isinstance(red_pool, list) and red_pool:
                red_pool_sizes.append(len(red_pool))
            if isinstance(blue_pool, list) and blue_pool:
                blue_pool_sizes.append(len(blue_pool))
        replacements = payload.get("diversity_replacements", []) or []
        if isinstance(replacements, list) and replacements:
            diversity_trigger_count += 1
        matrix = payload.get("matrix", {})
        if isinstance(matrix, dict) and not matrix_type:
            matrix_type = str(matrix.get("type", "")).strip()

    total_records = max(len(records), 1)
    avg_red_pool = max(red_pool_sizes) if red_pool_sizes else 10
    avg_blue_pool = max(blue_pool_sizes) if blue_pool_sizes else 3
    preferred_rows = []
    for row in matrix_ranking:
        try:
            row_id = int(row.get("row_id"))
        except Exception:
            continue
        if 1 <= row_id <= 5 and row_id not in preferred_rows:
            preferred_rows.append(row_id)
    for row_id in range(1, 6):
        if row_id not in preferred_rows:
            preferred_rows.append(row_id)
    diversity_rate = diversity_trigger_count / total_records

    return {
        "version": 1,
        "origin": "analyze_archive",
        "pool_params": {
            "core_red_pool_size": int(avg_red_pool),
            "core_blue_pool_size": int(avg_blue_pool),
        },
        "fusion_params": {
            "ticket_decay_step": 0.08,
            "min_ticket_decay": 0.65,
            "diversity_trigger_rate": round(diversity_rate, 6),
        },
        "matrix_params": {
            "matrix_type": matrix_type or (str(matrix_ranking[0].get("matrix_type", "")) if matrix_ranking else ""),
            "preferred_rows": preferred_rows,
        },
    }


def write_latest_weight_patch(source_patch_path: str, latest_patch_path: str = "config/weight_patch.latest.json") -> str:
    with open(source_patch_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    parent = os.path.dirname(latest_patch_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(latest_patch_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return latest_patch_path


def write_latest_matrix_patch(source_patch_path: str, latest_patch_path: str = "config/matrix_patch.latest.json") -> str:
    with open(source_patch_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    parent = os.path.dirname(latest_patch_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(latest_patch_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return latest_patch_path


def write_latest_param_patch(source_patch_path: str, latest_patch_path: str = "config/param_patch.latest.json") -> str:
    with open(source_patch_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    parent = os.path.dirname(latest_patch_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(latest_patch_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return latest_patch_path


def export_reports(
    export_prefix: str,
    all_time_ranking: List[Dict[str, object]],
    recent_ranking: List[Dict[str, object]],
    delta_ranking: List[Dict[str, object]],
    suggestions: List[str],
    weight_adjustments: Optional[List[Dict[str, object]]] = None,
    matrix_ranking: Optional[List[Dict[str, object]]] = None,
    records: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, str]:
    base = export_prefix
    root, ext = os.path.splitext(base)
    if ext.lower() in {".json", ".csv"}:
        base = root
    json_path = f"{base}.json"
    csv_path = f"{base}.csv"
    weight_patch_path = f"{base}.weight_patch.json"
    matrix_patch_path = f"{base}.matrix_patch.json"
    param_patch_path = f"{base}.param_patch.json"
    payload = {
        "all_time_ranking": all_time_ranking,
        "recent_ranking": recent_ranking,
        "delta_ranking": delta_ranking,
        "weight_adjustments": weight_adjustments or [],
        "matrix_ranking": matrix_ranking or [],
        "suggestions": suggestions,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["agent", "all_time_score", "recent_score", "delta", "weight_delta"],
        )
        writer.writeheader()
        all_map = _ranking_to_map(all_time_ranking)
        recent_map = _ranking_to_map(recent_ranking)
        weight_map = {str(x["agent"]): x for x in (weight_adjustments or [])}
        agents = sorted(set(all_map.keys()) | set(recent_map.keys()))
        for agent in agents:
            writer.writerow(
                {
                    "agent": agent,
                    "all_time_score": all_map.get(agent, {}).get("score", 0.0),
                    "recent_score": recent_map.get(agent, {}).get("score", 0.0),
                    "delta": next((r["delta"] for r in delta_ranking if r["agent"] == agent), 0.0),
                    "weight_delta": weight_map.get(agent, {}).get("weight_delta", 0.0),
                }
            )
    patch_payload = build_weight_patch_payload(all_time_ranking, weight_adjustments or [])
    with open(weight_patch_path, "w", encoding="utf-8") as f:
        json.dump(patch_payload, f, ensure_ascii=False, indent=2)
    matrix_patch_payload = build_matrix_patch_payload(matrix_ranking or [])
    with open(matrix_patch_path, "w", encoding="utf-8") as f:
        json.dump(matrix_patch_payload, f, ensure_ascii=False, indent=2)
    param_patch_payload = build_param_patch_payload(records or [], matrix_ranking or [])
    with open(param_patch_path, "w", encoding="utf-8") as f:
        json.dump(param_patch_payload, f, ensure_ascii=False, indent=2)
    return {
        "json": json_path,
        "csv": csv_path,
        "weight_patch": weight_patch_path,
        "matrix_patch": matrix_patch_path,
        "param_patch": param_patch_path,
    }


def render_report(
    archive_dir: str,
    limit_files: Optional[int] = None,
    top_k: int = 10,
    recent_limit: Optional[int] = None,
    suggest_step: float = 0.02,
) -> str:
    records = collect_explain_json_records(archive_dir, limit_files=limit_files)
    ranking = build_agent_ranking(records)
    recent_records = records if not recent_limit else records[-max(1, int(recent_limit)) :]
    recent_ranking = build_agent_ranking(recent_records)
    delta_ranking = compute_dual_view_delta(recent_ranking, ranking)
    weight_adjustments = build_weight_adjustments(recent_ranking, ranking, step=suggest_step)
    matrix_ranking = build_matrix_row_ranking(records)
    suggestions = build_tuning_suggestions(ranking, records)

    lines = []
    lines.append(f"归档目录: {archive_dir}")
    lines.append(f"解析到 explain_json 的票据数: {len(records)}")
    lines.append("")
    lines.append("Agent 命中贡献排行榜（有真实结果时只统计命中球贡献）:")
    for idx, row in enumerate(ranking[: max(1, int(top_k))], start=1):
        lines.append(
            f"  {idx:02d}. {row['agent']:8s} score={row['score']:.6f} | 来源占比={row['source_share']:.2%} | 来源次数={row['source_count']}"
        )
    lines.append("")
    lines.append("双视角差异（最近N期 - 全历史）:")
    for idx, row in enumerate(delta_ranking[: max(1, int(top_k))], start=1):
        lines.append(
            f"  {idx:02d}. {row['agent']:8s} recent={row['recent_score']:.6f} | all={row['all_time_score']:.6f} | delta={row['delta']:+.6f}"
        )
    lines.append("")
    lines.append("建议权重增减量:")
    for idx, row in enumerate(weight_adjustments[: max(1, int(top_k))], start=1):
        lines.append(f"  {idx:02d}. {row['agent']:8s} 建议 Δw={row['weight_delta']:+.4f} | delta={row['delta']:+.6f}")
    lines.append("")
    if matrix_ranking:
        lines.append("矩阵行表现:")
        for idx, row in enumerate(matrix_ranking[: max(1, int(top_k))], start=1):
            lines.append(
                f"  {idx:02d}. type={row['matrix_type']} | row={row['row_id']} | samples={row['samples']} | "
                f"avg_score={row['avg_score']:.6f} | red_hit_avg={row['red_hit_avg']:.6f} | "
                f"blue_hit_rate={row['blue_hit_rate']:.2%} | hit_rate_ge2={row['hit_rate_ge2']:.2%} | hit_rate_ge3={row['hit_rate_ge3']:.2%}"
            )
        lines.append("")
    lines.append("调参建议:")
    for item in suggestions:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="分析 prediction_archive 中的 explain_json，输出贡献排行榜与调参建议")
    parser.add_argument("--archive-dir", default="prediction_archive", help="归档目录路径（默认 prediction_archive）")
    parser.add_argument("--limit-files", type=int, default=None, help="最多分析多少个归档文件（默认全部）")
    parser.add_argument("--top-k", type=int, default=10, help="排行榜显示前K名（默认10）")
    parser.add_argument("--recent-limit", type=int, default=20, help="最近N张票据视角（默认20）")
    parser.add_argument("--suggest-step", type=float, default=0.02, help="建议权重变动幅度上限（默认0.02）")
    parser.add_argument("--export-prefix", default=None, help="导出报告路径前缀（不带扩展名）")
    parser.add_argument("--latest-patch-path", default="config/weight_patch.latest.json", help="固定写回权重补丁路径")
    parser.add_argument("--latest-matrix-patch-path", default="config/matrix_patch.latest.json", help="固定写回矩阵补丁路径")
    parser.add_argument("--latest-param-patch-path", default="config/param_patch.latest.json", help="固定写回参数补丁路径")
    args = parser.parse_args()
    records = collect_explain_json_records(args.archive_dir, limit_files=args.limit_files)
    all_time_ranking = build_agent_ranking(records)
    recent_records = records[-max(1, int(args.recent_limit)) :] if records else []
    recent_ranking = build_agent_ranking(recent_records)
    delta_ranking = compute_dual_view_delta(recent_ranking, all_time_ranking)
    weight_adjustments = build_weight_adjustments(recent_ranking, all_time_ranking, step=args.suggest_step)
    matrix_ranking = build_matrix_row_ranking(records)
    suggestions = build_tuning_suggestions(all_time_ranking, records)

    print(
        render_report(
            args.archive_dir,
            limit_files=args.limit_files,
            top_k=args.top_k,
            recent_limit=args.recent_limit,
            suggest_step=args.suggest_step,
        )
    )
    if args.export_prefix:
        paths = export_reports(
            args.export_prefix,
            all_time_ranking=all_time_ranking,
            recent_ranking=recent_ranking,
            delta_ranking=delta_ranking,
            suggestions=suggestions,
            weight_adjustments=weight_adjustments,
            matrix_ranking=matrix_ranking,
            records=records,
        )
        latest_path = write_latest_weight_patch(paths["weight_patch"], args.latest_patch_path)
        latest_matrix_path = write_latest_matrix_patch(paths["matrix_patch"], args.latest_matrix_patch_path)
        latest_param_path = write_latest_param_patch(paths["param_patch"], args.latest_param_patch_path)
        print(f"\n已导出 JSON: {paths['json']}")
        print(f"已导出 CSV : {paths['csv']}")
        print(f"已导出权重补丁: {paths['weight_patch']}")
        print(f"已导出矩阵补丁: {paths['matrix_patch']}")
        print(f"已导出参数补丁: {paths['param_patch']}")
        print(f"已写回最新补丁: {latest_path}")
        print(f"已写回最新矩阵补丁: {latest_matrix_path}")
        print(f"已写回最新参数补丁: {latest_param_path}")


if __name__ == "__main__":
    main()
