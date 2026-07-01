#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
升降台功能模拟测试（无真实 CAN）。

模拟 CANopen CiA402 SDO，验证各按钮对应的底层 API 能否被调用并产生预期效果。
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from openflex_driver._lib.lift_canopen import (  # noqa: E402
    CMD_ENABLE_OPERATION,
    DI_CONFIG_INDICES,
    MODE_POSITION,
    MODE_VELOCITY,
    OD_CONTROL_WORD,
    OD_DIGITAL_INPUTS,
    OD_MODE_OF_OPERATION,
    OD_MODE_OF_OPERATION_DISPLAY,
    OD_POSITION_ACTUAL,
    OD_PROFILE_ACCELERATION,
    OD_PROFILE_DECELERATION,
    OD_PROFILE_VELOCITY,
    OD_STATUS_WORD,
    OD_TARGET_POSITION,
    OD_TARGET_VELOCITY,
    OD_VELOCITY_ACTUAL,
    SW_OPERATION_ENABLED,
    SW_TARGET_REACHED,
)
from openflex_driver.column import Column, CONTROL_MODE_POSITION, CONTROL_MODE_VELOCITY  # noqa: E402

# ---------------------------------------------------------------------------
# 模拟伺服状态
# ---------------------------------------------------------------------------

COUNTS_PER_M = 2_000_000.0
INVERT_FEEDBACK = True
INVERT_COMMAND = True
MOTION_STEP_M = 0.008  # 每次反馈读取时的位移步长

STATE: Dict[str, Any] = {
    "physical_m": 0.22,
    "velocity_mps": 0.0,
    "statusword": 0x0040,
    "mode": MODE_VELOCITY,
    "position_reached": False,
    "di_config": {idx: 0 for idx in DI_CONFIG_INDICES.values()},
}

CALL_LOG: List[Tuple[str, Any]] = []


def _log(name: str, detail: Any = None):
    CALL_LOG.append((name, detail))


def _physical_to_counts(physical_m: float) -> int:
    counts = int(round(physical_m * COUNTS_PER_M))
    return -counts if INVERT_FEEDBACK else counts


def _counts_to_physical(counts: int) -> float:
    physical = -counts if INVERT_FEEDBACK else counts
    return physical / COUNTS_PER_M


def _velocity_counts_to_mps(counts: int) -> float:
    physical = -counts if INVERT_FEEDBACK else counts
    return physical / COUNTS_PER_M


def _velocity_mps_to_counts(velocity_mps: float) -> int:
    counts = int(round(velocity_mps * COUNTS_PER_M))
    return -counts if INVERT_COMMAND else counts


def _build_di_raw(physical_m: float) -> int:
    """cia_not=bit0, cia_pot=bit1, cia_home=bit2；bit24~29 为物理 DI 电平。"""
    tol = 0.008
    raw = 0x3F << 24  # 物理 DI 默认高电平（未触发）
    if physical_m >= 0.44 - tol:
        raw |= 1 << 0
        raw &= ~(1 << 29)  # DI6 触发
    if physical_m <= 0.0 + tol:
        raw |= 1 << 1
        raw &= ~(1 << 28)  # DI5 触发
    if abs(physical_m - 0.10) <= tol:
        raw |= 1 << 2
        raw &= ~(1 << 27)  # DI4 触发
    return raw


def _advance_motion():
    vel = float(STATE["velocity_mps"])
    if abs(vel) < 1e-6:
        return
    step = MOTION_STEP_M if vel > 0 else -MOTION_STEP_M
    STATE["physical_m"] = max(-0.01, min(0.46, STATE["physical_m"] + step))
    STATE["velocity_mps"] = vel


def mock_verify_can(up: bool = True):
    def _fn(interface, log=None):
        _log("verify_can_interface", interface)
        return up

    return _fn


def mock_sdo_read(
    can_interface: str,
    node_id: int,
    index: int,
    subindex: int = 0,
    timeout: float = 0.15,
) -> Optional[int]:
    _log("sdo_read_i32", (index, subindex))
    _advance_motion()

    if index == OD_STATUS_WORD:
        sw = int(STATE["statusword"])
        if STATE.get("position_reached"):
            sw |= SW_TARGET_REACHED
        return sw
    if index == OD_POSITION_ACTUAL:
        return _physical_to_counts(float(STATE["physical_m"]))
    if index == OD_VELOCITY_ACTUAL:
        return int(round(float(STATE["velocity_mps"]) * COUNTS_PER_M))
    if index == OD_DIGITAL_INPUTS:
        return _build_di_raw(float(STATE["physical_m"]))
    if index == OD_MODE_OF_OPERATION:
        return int(STATE["mode"])
    if index == OD_MODE_OF_OPERATION_DISPLAY:
        return int(STATE["mode"])
    if index in DI_CONFIG_INDICES.values():
        return int(STATE["di_config"].get(index, 0))
    return 0


def mock_sdo_write(
    can_interface: str,
    node_id: int,
    index: int,
    subindex: int,
    value: int,
    size: int,
    timeout: float = 0.15,
) -> bool:
    _log("sdo_write_i32", (index, subindex, value, size))
    val = int(value)

    if index == OD_CONTROL_WORD:
        if val & CMD_ENABLE_OPERATION == CMD_ENABLE_OPERATION:
            STATE["statusword"] = SW_OPERATION_ENABLED
        elif val == 0:
            STATE["statusword"] = 0x0040
            STATE["velocity_mps"] = 0.0
        return True

    if index == OD_MODE_OF_OPERATION:
        STATE["mode"] = val
        return True

    if index == OD_TARGET_VELOCITY:
        STATE["velocity_mps"] = _velocity_counts_to_mps(val)
        STATE["position_reached"] = False
        return True

    if index == OD_TARGET_POSITION:
        STATE["physical_m"] = _counts_to_physical(val)
        STATE["position_reached"] = True
        STATE["velocity_mps"] = 0.0
        return True

    if index in DI_CONFIG_INDICES.values():
        STATE["di_config"][index] = val
        return True

    if index in (
        OD_PROFILE_ACCELERATION,
        OD_PROFILE_DECELERATION,
        OD_PROFILE_VELOCITY,
    ):
        return True

    return True


def mock_sleep(seconds: float):
    _log("time.sleep", seconds)


PATCHES = [
    patch("openflex_driver._lib.can_utils.verify_can_interface", mock_verify_can(True)),
    patch("openflex_driver.column.verify_can_interface", mock_verify_can(True)),
    patch("openflex_driver.column.sdo_read_i32", mock_sdo_read),
    patch("openflex_driver.column.sdo_write_i32", mock_sdo_write),
    patch("openflex_driver.column.time.sleep", mock_sleep),
    patch("openflex_driver.column.Column._send_rpdo1", lambda self, *a, **k: True),
]


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""
        self.calls: List[str] = []


def _calls_since(start: int) -> List[str]:
    return [c[0] for c in CALL_LOG[start:]]


def run_case(name: str, fn: Callable[[], None], expect_calls: List[str]) -> TestResult:
    res = TestResult(name)
    start = len(CALL_LOG)
    try:
        fn()
        actual = _calls_since(start)
        missing = [c for c in expect_calls if c not in actual]
        if missing:
            res.detail = f"缺少底层调用: {missing}; 实际: {actual[:20]}{'...' if len(actual) > 20 else ''}"
        else:
            res.ok = True
            res.detail = f"底层调用数: {len(actual)} ({', '.join(dict.fromkeys(actual))})"
        res.calls = actual
    except Exception as exc:
        res.detail = f"异常: {exc}\n{traceback.format_exc()}"
    return res


def _reset_state(physical_m: float = 0.22):
    STATE["physical_m"] = physical_m
    STATE["velocity_mps"] = 0.0
    STATE["statusword"] = 0x0040
    STATE["mode"] = MODE_VELOCITY
    STATE["position_reached"] = False
    STATE["di_config"] = {idx: 0 for idx in DI_CONFIG_INDICES.values()}


def main() -> int:
    results: List[TestResult] = []
    for p in PATCHES:
        p.start()

    cal_fd, cal_path = tempfile.mkstemp(suffix=".yaml")
    os.close(cal_fd)
    if os.path.exists(cal_path):
        os.remove(cal_path)

    try:
        _reset_state()
        column = Column(
            can_interface="can3",
            node_id=16,
            counts_per_meter=COUNTS_PER_M,
            invert_command=INVERT_COMMAND,
            invert_feedback=INVERT_FEEDBACK,
            homing_timeout_sec=5.0,
            calibration_file=cal_path,
            log=lambda *a, **k: None,
        )

        # ---- 连接 ----
        results.append(
            run_case(
                "连接升降台",
                lambda: column.connect(),
                ["verify_can_interface", "sdo_read_i32"],
            )
        )
        assert column.is_connected

        # ---- 扫描 ----
        results.append(
            run_case(
                "扫描电机",
                lambda: (column.scan_motor() and True),
                ["sdo_read_i32"],
            )
        )

        # ---- 使能 ----
        results.append(
            run_case(
                "使能驱动",
                lambda: (column.enable() and column.is_enabled),
                ["sdo_write_i32", "sdo_read_i32"],
            )
        )

        # ---- 被动设零 ----
        def t_passive_zero():
            _reset_state(0.18)
            column.is_enabled = True
            column.homing_complete = False
            ok = column.set_passive_zero()
            assert ok and column.homing_complete
            assert abs(column.position_offset_m - 0.18) < 0.001

        results.append(
            run_case(
                "设零(被动/手动)",
                t_passive_zero,
                ["sdo_read_i32", "sdo_write_i32"],
            )
        )

        # ---- 移动到目标 ----
        def t_move_to():
            column.homing_complete = True
            column.position_offset_m = 0.18
            _reset_state(0.18)
            column.is_enabled = True
            column.control_mode = CONTROL_MODE_POSITION
            STATE["mode"] = MODE_POSITION
            ok = column.move_to_user_position(0.25, speed_mps=0.05)
            assert ok
            user_pos = column.get_status().get("position_m", 0.0)
            assert abs(user_pos - 0.25) < 0.02

        results.append(
            run_case(
                "移动到目标位置",
                t_move_to,
                ["sdo_write_i32"],
            )
        )

        # ---- 速度点动 ----
        def t_jog_up():
            column.homing_complete = True
            column.position_offset_m = 0.18
            _reset_state(0.18)
            column.is_enabled = True
            column.control_mode = CONTROL_MODE_POSITION
            STATE["mode"] = MODE_POSITION
            assert column.switch_to_velocity_mode()
            ok = column.jog_velocity(0.05)
            assert ok
            column.jog_velocity(0.0)

        results.append(
            run_case(
                "速度点动(上移)",
                t_jog_up,
                ["sdo_write_i32"],
            )
        )

        def t_jog_down():
            column.homing_complete = True
            column.position_offset_m = 0.18
            _reset_state(0.22)
            column.is_enabled = True
            column.control_mode = CONTROL_MODE_VELOCITY
            column._last_target_velocity_counts = None
            STATE["mode"] = MODE_VELOCITY
            column.refresh_status()
            ok = column.jog_velocity(-0.05)
            assert ok
            column.jog_velocity(0.0)

        results.append(
            run_case(
                "速度点动(下移)",
                t_jog_down,
                ["sdo_write_i32"],
            )
        )

        # ---- 回原点 ----
        def t_return_home():
            column.homing_complete = True
            column.position_offset_m = 0.18
            _reset_state(0.30 + 0.18)
            column.is_enabled = True
            column.control_mode = CONTROL_MODE_POSITION
            STATE["mode"] = MODE_POSITION
            ok = column.return_home()
            assert ok
            assert abs(column.read_homing_feedback().user_position_m) < 0.02

        results.append(
            run_case(
                "回原点(用户0m)",
                t_return_home,
                ["sdo_write_i32"],
            )
        )

        # ---- 停止 ----
        def t_stop():
            _reset_state(0.22)
            column.is_enabled = True
            column.control_mode = CONTROL_MODE_VELOCITY
            column._last_target_velocity_counts = None
            STATE["mode"] = MODE_VELOCITY
            column.stop_motion()

        results.append(
            run_case(
                "停止运动",
                t_stop,
                ["sdo_write_i32"],
            )
        )

        # ---- 主动设零 ----
        def t_active_zero():
            _reset_state(0.22)
            column.is_enabled = True
            column.homing_complete = False
            column.position_offset_m = 0.0
            ok = column.set_active_zero()
            assert ok and column.homing_complete

        results.append(
            run_case(
                "设零(主动/自动)",
                t_active_zero,
                ["sdo_write_i32", "sdo_read_i32"],
            )
        )

        # ---- 中止回零 ----
        def t_abort_homing():
            _reset_state(0.22)
            column.is_enabled = True
            column.homing_complete = False
            column.position_offset_m = 0.0
            column._abort_homing.clear()
            column.homing_in_progress = True
            column.homing_detail = "active_seek_upper"
            column.abort_homing()
            assert column._homing_aborted()

        results.append(
            run_case(
                "中止回零",
                t_abort_homing,
                [],
            )
        )

        # ---- 失能 ----
        results.append(
            run_case(
                "失能驱动",
                lambda: (column.disable() and not column.is_enabled),
                ["sdo_write_i32"],
            )
        )

        # ---- 急停 ----
        def t_estop():
            column.is_enabled = True
            STATE["statusword"] = SW_OPERATION_ENABLED
            ok = column.quick_stop()
            assert ok and not column.is_enabled

        results.append(
            run_case(
                "急停",
                t_estop,
                ["sdo_write_i32"],
            )
        )

        # ---- 监控/刷新状态 ----
        def t_monitor():
            column._connected = True
            _reset_state(0.20)
            column.refresh_status()
            st = column.get_status()
            assert st.get("can_interface") == "can3"
            assert st.get("node_id") == 16
            assert "position_m" in st

        results.append(
            run_case(
                "刷新状态(监控)",
                t_monitor,
                ["sdo_read_i32"],
            )
        )

        # ---- 模式切换（无 PP 移动）----
        def t_mode_switch_no_pp():
            column._connected = True
            column.is_enabled = True
            column.homing_complete = True
            column.homing_in_progress = False
            column.position_move_in_progress = False
            _reset_state(0.20)
            column.control_mode = CONTROL_MODE_VELOCITY
            column._position_pp_active = False
            STATE["mode"] = MODE_VELOCITY
            assert column.switch_to_position_mode()
            assert column.control_mode == CONTROL_MODE_POSITION
            assert STATE["mode"] == MODE_POSITION
            assert column.switch_to_velocity_mode()
            assert column.control_mode == CONTROL_MODE_VELOCITY
            assert STATE["mode"] == MODE_VELOCITY

        results.append(
            run_case(
                "模式切换(无PP移动)",
                t_mode_switch_no_pp,
                ["sdo_write_i32"],
            )
        )

        # ---- 模式切换（PP 移动后）----
        def t_mode_switch_after_pp():
            column._connected = True
            column.is_enabled = True
            column.homing_complete = True
            column.homing_in_progress = False
            column.position_move_in_progress = False
            column.position_offset_m = 0.18
            _reset_state(0.18)
            column.control_mode = CONTROL_MODE_POSITION
            STATE["mode"] = MODE_POSITION
            assert column.move_to_user_position(0.25, speed_mps=0.05)
            assert column._position_pp_active
            assert column.switch_to_velocity_mode()
            assert not column._position_pp_active
            assert column.control_mode == CONTROL_MODE_VELOCITY
            ok = column.jog_velocity(0.03)
            assert ok
            column.jog_velocity(0.0)

        results.append(
            run_case(
                "模式切换(PP移动后)",
                t_mode_switch_after_pp,
                ["sdo_write_i32"],
            )
        )

        # ---- 断开 ----
        def t_disconnect():
            column._connected = True
            column.enable()
            column.close()
            assert not column.is_connected

        results.append(
            run_case(
                "断开升降台",
                t_disconnect,
                ["sdo_write_i32"],
            )
        )

    finally:
        for p in PATCHES:
            p.stop()
        if os.path.exists(cal_path):
            os.remove(cal_path)

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print("=" * 72)
    print(f"升降台 Mock CAN 测试: {passed}/{total} 通过")
    print("=" * 72)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"[{mark}] {r.name}")
        print(f"       {r.detail.split(chr(10))[0]}")
    print("=" * 72)
    if passed < total:
        print("\n失败项详情:")
        for r in results:
            if not r.ok:
                print(f"\n--- {r.name} ---\n{r.detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
