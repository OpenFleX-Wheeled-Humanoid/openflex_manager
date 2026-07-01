#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
头部功能模拟测试（无真实 CAN）。

模拟电机状态与 CAN 收发，逐按钮/API 验证能否正确调用底层并产生预期输出。
"""

from __future__ import annotations

import math
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 模拟电机状态 & 调用记录
# ---------------------------------------------------------------------------

MOTOR_STATE: Dict[int, Dict[str, Any]] = {
    1: {
        "angle": 0.15,
        "velocity": 0.0,
        "torque": 0.1,
        "temperature": 32.0,
        "mode_status": "MIT",
        "fault_status": "OK",
    },
    2: {
        "angle": -0.08,
        "velocity": 0.0,
        "torque": 0.2,
        "temperature": 31.0,
        "mode_status": "MIT",
        "fault_status": "OK",
    },
}

CALL_LOG: List[Tuple[str, Any]] = []
NETWORK_DOWN_ONCE = False


class MockBus:
    channel = "can2"

    def shutdown(self):
        CALL_LOG.append(("bus.shutdown", None))


MOCK_BUS = MockBus()


def _log(name: str, detail: Any = None):
    CALL_LOG.append((name, detail))


def mock_get_motor_status_readonly(bus, motor_id, **kwargs):
    _log("get_motor_status_readonly", motor_id)
    info = MOTOR_STATE.get(motor_id, {}).copy()
    return 0, info


def mock_enable_motor(bus, motor_id, **kwargs):
    _log("enable_motor", motor_id)
    return 0


def mock_disable_motor(bus, motor_id, **kwargs):
    _log("disable_motor", motor_id)
    return 0


def mock_set_control_mode(bus, motor_id, mode="mit", **kwargs):
    global NETWORK_DOWN_ONCE
    _log("set_control_mode", (motor_id, mode))
    if NETWORK_DOWN_ONCE:
        NETWORK_DOWN_ONCE = False
        raise RuntimeError(
            "CAN message send failed (ID: 0x0400FD01): "
            "Failed to transmit: 网络已关闭 [Error Code 100]"
        )
    return 0


def mock_set_zero_sta_parameter(bus, motor_id, zero_sta, **kwargs):
    _log("set_zero_sta_parameter", (motor_id, zero_sta))
    return 0


def mock_set_motor_zero(bus, motor_id, **kwargs):
    _log("set_motor_zero", motor_id)
    if motor_id in MOTOR_STATE:
        MOTOR_STATE[motor_id]["angle"] = 0.0
    return 0


def mock_auto_calibrate_zero(bus, motor_id, **kwargs):
    _log("auto_calibrate_zero", motor_id)
    if motor_id in MOTOR_STATE:
        MOTOR_STATE[motor_id]["angle"] = 0.0
    return True, 0.0, 0.5, -0.5


def mock_head_auto_calibrate_zero_joint(
    head, motor_id, zero_pos_per=0.5, **kwargs
):
    _log("head_auto_calibrate_zero", (motor_id, zero_pos_per))
    if motor_id in MOTOR_STATE:
        MOTOR_STATE[motor_id]["angle"] = 0.0
    return True, 0.0, 0.5, -0.5


def mock_head_auto_calibrate_false_but_zeroed(
    head, motor_id, zero_pos_per=0.5, **kwargs
):
    """模拟底层返回失败但硬件零点已写入的情况。"""
    _log("head_auto_calibrate_zero_false_ok", motor_id)
    if motor_id in MOTOR_STATE:
        MOTOR_STATE[motor_id]["angle"] = 0.0
    return False, 0.0, 0.5, -0.5


def mock_mit_motion_control(bus, motor_id, **kwargs):
    _log("mit_motion_control", (motor_id, kwargs.get("position")))
    if motor_id in MOTOR_STATE and kwargs.get("position") is not None:
        MOTOR_STATE[motor_id]["angle"] = float(kwargs["position"])
    return 0, None, None


def mock_mit_motion_control_simple(bus, motor_id, **kwargs):
    mock_mit_motion_control(bus, motor_id, **kwargs)
    return 0


def mock_mit_move_to_zero(bus, motor_id, **kwargs):
    _log("mit_move_to_zero", motor_id)
    if motor_id in MOTOR_STATE:
        MOTOR_STATE[motor_id]["angle"] = 0.0
    return 0


def mock_verify_can(up: bool = True):
    def _fn(interface, log=None):
        _log("verify_can_interface", (interface, up))
        return up
    return _fn


PATCHES = [
    patch("can.Bus", side_effect=lambda **kw: (_log("can.Bus", kw.get("channel")), MOCK_BUS)[1]),
    patch("openflex_driver._lib.can_utils.verify_can_interface", mock_verify_can(True)),
    patch("openflex_driver.head.verify_can_interface", mock_verify_can(True)),
    patch("openflex_driver.arm.get_motor_status_readonly", mock_get_motor_status_readonly),
    patch("openflex_driver.arm.enable_motor", mock_enable_motor),
    patch("openflex_driver.arm.disable_motor", mock_disable_motor),
    patch("openflex_driver.arm.set_control_mode", mock_set_control_mode),
    patch("openflex_driver.arm.set_motor_zero", mock_set_motor_zero),
    patch("openflex_driver.arm.set_zero_sta_parameter", mock_set_zero_sta_parameter),
    patch("openflex_driver.arm.mit_motion_control", mock_mit_motion_control),
    patch("openflex_driver.arm.mit_move_to_zero", mock_mit_move_to_zero),
    patch("openflex_driver.head.get_motor_status_readonly", mock_get_motor_status_readonly),
    patch("openflex_driver.head.disable_motor", mock_disable_motor),
    patch("openflex_driver.head.set_control_mode", mock_set_control_mode),
    patch("openflex_driver.head.set_motor_zero", mock_set_motor_zero),
    patch("openflex_driver.head.set_zero_sta_parameter", mock_set_zero_sta_parameter),
    patch(
        "openflex_driver.head.Head._auto_calibrate_zero_joint",
        mock_head_auto_calibrate_zero_joint,
    ),
    patch("openflex_driver.head.mit_motion_control_simple", mock_mit_motion_control_simple),
]


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""
        self.calls: List[str] = []


def _calls_since(clear_before: int) -> List[str]:
    return [c[0] for c in CALL_LOG[clear_before:]]


def run_case(name: str, fn: Callable[[], None], expect_calls: List[str]) -> TestResult:
    res = TestResult(name)
    start = len(CALL_LOG)
    try:
        fn()
        actual = _calls_since(start)
        missing = [c for c in expect_calls if c not in actual]
        if missing:
            res.detail = f"缺少底层调用: {missing}; 实际: {actual}"
        else:
            res.ok = True
            res.detail = f"底层调用: {actual}"
        res.calls = actual
    except Exception as exc:
        res.detail = f"异常: {exc}\n{traceback.format_exc()}"
    return res


def main() -> int:
    from openflex_driver.head import Head, JOINT_YAW, JOINT_PITCH

    results: List[TestResult] = []

    # 应用全部 patch 后创建 Head
    for p in PATCHES:
        p.start()

    try:
        head = Head(can_channel="can2", auto_enable_can=False, log=lambda *a, **k: None)
        head.bus = MOCK_BUS

        # ---- 连接头部 ----
        def t_connect():
            head.connect()

        results.append(run_case(
            "连接头部",
            t_connect,
            ["verify_can_interface"],
        ))

        # ---- 使能 ----
        def t_enable():
            r = head.enable(verbose=False)
            assert all(v == 0 for v in r.values()), r

        results.append(run_case(
            "使能（全部）",
            t_enable,
            ["enable_motor", "set_control_mode"],
        ))

        # ---- 刷新状态 / 检查电机 ----
        def t_status():
            st = head.get_joint_status()
            assert JOINT_YAW in st and JOINT_PITCH in st
            assert st[JOINT_YAW]["angle"] is not None

        results.append(run_case(
            "检查电机状态 / 刷新",
            t_status,
            ["get_motor_status_readonly"],
        ))

        # ---- 关节 +/- ----
        before_yaw = MOTOR_STATE[JOINT_YAW]["angle"]

        def t_move_yaw_plus():
            rc = head.move_joint_delta(JOINT_YAW, math.radians(5.0))
            assert rc == 0
            assert MOTOR_STATE[JOINT_YAW]["angle"] != before_yaw

        results.append(run_case(
            "偏航 + 步进",
            t_move_yaw_plus,
            ["get_motor_status_readonly", "mit_motion_control"],
        ))

        def t_move_pitch_minus():
            rc = head.move_joint_delta(JOINT_PITCH, math.radians(-5.0))
            assert rc == 0

        results.append(run_case(
            "俯仰 - 步进",
            t_move_pitch_minus,
            ["get_motor_status_readonly", "mit_motion_control"],
        ))

        # ---- 手动设零（单电机）----
        MOTOR_STATE[JOINT_YAW]["angle"] = 0.12

        def t_manual_yaw():
            rc = head.set_zero_passive(motor_id=JOINT_YAW, verbose=False)
            assert rc == 0
            assert abs(MOTOR_STATE[JOINT_YAW]["angle"]) < 0.05

        results.append(run_case(
            "偏航 手动设零",
            t_manual_yaw,
            ["get_motor_status_readonly", "disable_motor", "set_zero_sta_parameter", "set_motor_zero"],
        ))

        def t_manual_pitch():
            MOTOR_STATE[JOINT_PITCH]["angle"] = -0.1
            rc = head.set_zero_passive(motor_id=JOINT_PITCH, verbose=False)
            assert rc == 0

        results.append(run_case(
            "俯仰 手动设零",
            t_manual_pitch,
            ["set_motor_zero"],
        ))

        # ---- 自动设零（单电机）----
        def t_auto_yaw():
            MOTOR_STATE[JOINT_YAW]["angle"] = 0.2
            r = head.set_zero_active(motor_id=JOINT_YAW, verbose=False)
            assert r[JOINT_YAW]["success"]
            assert r[JOINT_YAW]["zero_pos_per"] == 0.5

        results.append(run_case(
            "偏航 自动设零",
            t_auto_yaw,
            ["disable_motor", "set_control_mode", "head_auto_calibrate_zero", "get_motor_status_readonly"],
        ))

        def t_auto_pitch():
            MOTOR_STATE[JOINT_PITCH]["angle"] = -0.15
            r = head.set_zero_active(motor_id=JOINT_PITCH, verbose=False)
            assert r[JOINT_PITCH]["success"]
            assert r[JOINT_PITCH]["zero_pos_per"] == 0.75

        results.append(run_case(
            "俯仰 自动设零",
            t_auto_pitch,
            ["head_auto_calibrate_zero"],
        ))

        def t_zero_position_formula():
            from openflex_driver.head import Head

            zero = Head._compute_active_zero_position(1.0, -1.0, 0.5)
            assert abs(zero) < 1e-9
            zero_pitch = Head._compute_active_zero_position(1.0, -1.0, 0.75)
            assert abs(zero_pitch - 0.5) < 1e-9

        results.append(run_case(
            "自动设零零点公式",
            t_zero_position_formula,
            [],
        ))

        def t_auto_yaw_false_report():
            MOTOR_STATE[JOINT_YAW]["angle"] = 0.0
            with patch(
                "openflex_driver.head.Head._auto_calibrate_zero_joint",
                mock_head_auto_calibrate_false_but_zeroed,
            ):
                r = head.set_zero_active(motor_id=JOINT_YAW, verbose=False)
            assert r[JOINT_YAW]["success"], r[JOINT_YAW]

        results.append(run_case(
            "偏航 自动设零误报修复",
            t_auto_yaw_false_report,
            ["disable_motor", "set_control_mode", "get_motor_status_readonly"],
        ))

        # ---- 回零（单电机 MIT）----
        MOTOR_STATE[JOINT_YAW]["angle"] = 0.3

        def t_home_yaw():
            rc = head.go_home(motor_id=JOINT_YAW, verbose=False)
            assert rc == 0
            assert abs(MOTOR_STATE[JOINT_YAW]["angle"]) < 1e-6

        results.append(run_case(
            "偏航 回零",
            t_home_yaw,
            ["get_motor_status_readonly", "mit_motion_control"],
        ))

        MOTOR_STATE[JOINT_PITCH]["angle"] = -0.25

        def t_home_pitch():
            rc = head.go_home(motor_id=JOINT_PITCH, verbose=False)
            assert rc == 0

        results.append(run_case(
            "俯仰 回零",
            t_home_pitch,
            ["get_motor_status_readonly", "mit_motion_control"],
        ))

        # ---- 断开连接（模拟已使能状态下断开）----
        head.is_enabled = True

        def t_disconnect():
            head.disconnect()
            assert head.bus is None
            assert head.is_enabled is False

        results.append(run_case(
            "断开连接",
            t_disconnect,
            ["disable_motor", "bus.shutdown"],
        ))

        # ---- 失能 ----
        head.bus = MOCK_BUS
        head.is_enabled = True

        def t_disable():
            r = head.disable(verbose=False)
            assert all(v == 0 for v in r.values())

        results.append(run_case(
            "失能（全部）",
            t_disable,
            ["disable_motor"],
        ))

        # ---- 旧 bus 网络关闭时，使能应重建 CAN bus 后重试 ----
        head.bus = MOCK_BUS
        head.is_enabled = False

        def t_enable_retry_network_down():
            global NETWORK_DOWN_ONCE
            NETWORK_DOWN_ONCE = True
            r = head.enable_motor_by_id(JOINT_YAW, verbose=False)
            assert r == 0

        results.append(run_case(
            "使能重试（网络已关闭后重建 bus）",
            t_enable_retry_network_down,
            ["set_control_mode", "bus.shutdown", "can.Bus", "enable_motor"],
        ))

        # ---- CAN 未 UP 时连接应失败 ----
        with patch(
            "openflex_driver.head.verify_can_interface",
            mock_verify_can(False),
        ):
            head2 = Head(can_channel="can2", auto_enable_can=False, log=lambda *a, **k: None)
            head2.bus = MOCK_BUS

            def t_connect_fail():
                try:
                    head2.connect()
                    raise AssertionError("应抛出 RuntimeError")
                except RuntimeError:
                    pass

            r = run_case("连接失败（CAN DOWN）", t_connect_fail, ["verify_can_interface"])
            results.append(r)

    finally:
        for p in PATCHES:
            p.stop()

    # ---- 输出报告 ----
    print("=" * 72)
    print("头部功能模拟测试报告（无真实 CAN）")
    print("=" * 72)
    print(f"模拟电机初始状态: yaw={MOTOR_STATE[1]}, pitch={MOTOR_STATE[2]}")
    print()

    passed = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"[{mark}] {r.name}")
        print(f"       {r.detail}")
        if r.ok:
            passed += 1
        print()

    print("-" * 72)
    print(f"合计: {passed}/{len(results)} 通过")
    print(f"总底层调用次数: {len(CALL_LOG)}")
    print("-" * 72)

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
