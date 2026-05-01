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
    core_red_pool_size: int = 10
    core_blue_pool_size: int = 3
    rotation_matrix_type: str = "10_red_guard_6_to_5"
    rotation_matrix_rows: Tuple[Tuple[int, ...], ...] = field(
        default_factory=lambda: (
            (0, 1, 2, 3, 4, 5),
            (0, 1, 2, 6, 7, 8),
            (0, 3, 4, 6, 7, 9),
            (1, 3, 5, 6, 8, 9),
            (2, 4, 5, 7, 8, 9),
        )
    )
    
    ticket_decay_step: float = 0.08
    min_ticket_decay: float = 0.65
    learning_rate: float = 0.15
    decay_gamma: float = 0.88
    default_learn_cycles: int = 24
    
    hot_cold_window: int = 40
    blue_pattern_window: int = 20
    blue_parity_window: int = 10
    cycle_max_period: int = 50
    sum_trend_periods: int = 30
    zone_balance_periods: int = 20
    position_analysis_periods: int = 60
    
    min_ticket_weight: float = 0.03
    min_pool_score: float = 0.0001
    diversity_overlap_threshold: int = 4
    diversity_max_attempts: int = 4
    diversity_penalty_factor: float = 0.62
    
    blue_repeat_high_rate: float = 0.08
    blue_repeat_bonus: float = 1.5
    blue_repeat_penalty: float = 0.8
    missing_threshold: int = 20
    missing_bonus: float = 1.15
    missing_penalty: float = 0.9
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
            },
            "matrix_params": {
                "matrix_type": self.rotation_matrix_type,
                "preferred_rows": list(range(1, row_count + 1)),
                "row_weights": {str(i): 1.0 / row_count for i in range(1, row_count + 1)},
            },
        }


GLOBAL_CONFIG = ProjectConfig()
