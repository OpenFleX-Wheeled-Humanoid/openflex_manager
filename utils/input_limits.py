#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户输入范围与精度 — 对齐 URDF / ROS 工具 / 驱动默认值。

参考:
  - openarmx_head joint_limits.yaml (±90°)
  - HeadJointSliderPanel 步长 1–200 mrad
  - lift_slide URDF (0–0.45 m, 0.10 m/s)
  - chassis steering ±90°, UM ±330 RPM
"""

from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# 头部 (RS00, 2-DOF)
# ---------------------------------------------------------------------------

HEAD_JOINT_LIMIT_RAD = math.pi / 2.0
HEAD_JOINT_LIMIT_DEG = 90.0

# HeadJointSliderPanel: 1–200 mrad per cycle
HEAD_STEP_MIN_MRAD = 1
HEAD_STEP_MAX_MRAD = 200
HEAD_STEP_MIN_DEG = HEAD_STEP_MIN_MRAD / 1000.0 * 180.0 / math.pi
HEAD_STEP_MAX_DEG = HEAD_STEP_MAX_MRAD / 1000.0 * 180.0 / math.pi
HEAD_STEP_DECIMALS = 1
HEAD_STEP_SINGLE_STEP_DEG = 0.1

# ---------------------------------------------------------------------------
# 升降台 (lift slide)
# ---------------------------------------------------------------------------

COLUMN_POSITION_MIN_M = 0.0
COLUMN_POSITION_MAX_M = 0.45
COLUMN_POSITION_DECIMALS = 4
COLUMN_POSITION_SINGLE_STEP_M = 0.001

COLUMN_SPEED_MIN_MPS = 0.001
COLUMN_SPEED_MAX_MPS = 0.10
COLUMN_SPEED_DECIMALS = 3
COLUMN_SPEED_SINGLE_STEP_MPS = 0.001

COLUMN_STEP_MIN_MM = 0.1
COLUMN_STEP_DECIMALS = 1
COLUMN_STEP_SINGLE_STEP_MM = 0.1

# ---------------------------------------------------------------------------
# 底盘 (RS 转向 + UM 驱动)
# ---------------------------------------------------------------------------

CHASSIS_STEERING_LIMIT_DEG = 90.0
CHASSIS_STEERING_LIMIT_RAD = math.pi / 2.0
CHASSIS_STEERING_DECIMALS = 1
CHASSIS_STEERING_SINGLE_STEP_DEG = 0.5

CHASSIS_DRIVING_MAX_RPM = 330.0
CHASSIS_DRIVING_DECIMALS = 0
CHASSIS_DRIVING_SINGLE_STEP_RPM = 1.0


def clamp(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))


def configure_double_spinbox(
    spin,
    lo: float,
    hi: float,
    decimals: int,
    single_step: float,
    value: Optional[float] = None,
) -> None:
    """配置 QDoubleSpinBox 范围/精度，并将当前值钳位到合法区间。"""
    if lo > hi:
        lo, hi = hi, lo
    spin.setDecimals(int(decimals))
    spin.setSingleStep(float(single_step))
    spin.setRange(float(lo), float(hi))
    target = spin.value() if value is None else float(value)
    spin.setValue(clamp(target, lo, hi))
