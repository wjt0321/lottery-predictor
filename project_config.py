#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目共享配置模块"""

import os
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class ProjectConfig:
    """项目全局配置类"""
    data_file: str = "lottery_data.json"
    archive_dir: str = "prediction_archive"
    config_dir: str = "config"
    
    draw_weekdays: Tuple[int, ...] = (1, 3, 6)
    draw_cutoff_hour: int = 21
    draw_cutoff_minute: int = 30
    
    team_ticket_count: int = 5
    core_red_pool_size: int = 22
    core_blue_pool_size: int = 10
    rotation_matrix_type: str = "22_red_cover_6_to_5"
    rotation_matrix_rows: Tuple[Tuple[int, ...], ...] = field(
        default_factory=lambda: (
            (0, 1, 2, 3, 4, 5),
            (6, 7, 8, 9, 10, 11),
            (12, 13, 14, 15, 16, 17),
            (18, 19, 20, 21, 0, 6),
            (1, 7, 12, 18, 3, 9),
        )
    )
    
    ticket_decay_step: float = 0.06
    min_ticket_decay: float = 0.55
    learning_rate: float = 0.25
    decay_gamma: float = 0.85
    default_learn_cycles: int = 30

    hot_cold_window: int = 50
    blue_pattern_window: int = 30
    blue_parity_window: int = 15
    cycle_max_period: int = 60
    sum_trend_periods: int = 40
    zone_balance_periods: int = 30
    position_analysis_periods: int = 60

    min_ticket_weight: float = 0.02
    min_pool_score: float = 0.0001

    # 蓝球引擎参数（统一配置入口，通过 dict 传入 BlueBallEngine）
    blue_missing_cold_threshold: int = 20
    blue_missing_cold_bonus: float = 1.8
    blue_missing_extreme_threshold: int = 40
    blue_missing_extreme_bonus: float = 2.5
    blue_parity_window: int = 15
    blue_zone_window: int = 30
    blue_amplitude_window: int = 30
    blue_heat_window: int = 20
    blue_cold_chase_cap: int = 3

    # 位置权重参数
    pos_weight_min: float = 0.6
    pos_weight_max: float = 1.5
    
    def ensure_dirs(self) -> None:
        """确保必要的目录存在"""
        for directory in [self.archive_dir, self.config_dir]:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
    
    def to_runtime_config(self) -> Dict:
        """转换为运行时配置字典"""
        row_count = len(self.rotation_matrix_rows)
        return {
            "pool_params": {
                "core_red_pool_size": self.core_red_pool_size,
                "core_blue_pool_size": self.core_blue_pool_size,
            },
            "fusion_params": {
                "ticket_decay_step": self.ticket_decay_step,
                "min_ticket_decay": self.min_ticket_decay,
                "debate_factor": 0.6,
            },
            "matrix_params": {
                "matrix_type": self.rotation_matrix_type,
                "preferred_rows": [],
                "row_weights": {str(i): 1.0 / row_count for i in range(1, row_count + 1)},
            },
            "blue_params": {
                "missing_cold_threshold": self.blue_missing_cold_threshold,
                "missing_cold_bonus": self.blue_missing_cold_bonus,
                "missing_extreme_threshold": self.blue_missing_extreme_threshold,
                "missing_extreme_bonus": self.blue_missing_extreme_bonus,
                "parity_window": self.blue_parity_window,
                "zone_window": self.blue_zone_window,
                "amplitude_window": self.blue_amplitude_window,
                "heat_window": self.blue_heat_window,
                "cold_chase_cap": self.blue_cold_chase_cap,
            },
            "cover_mode": {
                "ticket_count": self.team_ticket_count,
                "candidate_pool_size": self.core_red_pool_size,
                "blue_bucket_size": self.core_blue_pool_size,
                "score_weights": {
                    "red_hit_ge2": 0.40,
                    "red_hit_ge3": 0.25,
                    "blue_pool_hit": 0.20,
                    "diversity": 0.15,
                },
            },
        }


GLOBAL_CONFIG = ProjectConfig()
