#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底盘功能模拟测试（无真实 CAN）。

模拟 RS 转向 + UM 驱动，验证各按钮对应的底层 API 能否被调用并产生预期效果。
"""

from __future__ import annotations

import math
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from openflex_driver.chassis import MODULE_NAMES, Chassis  # noqa: E402

# ---------------------------------------------------------------------------
# 模拟状态
# ---------------------------------------------------------------------------

RS_STATE: Dict[int, Dict[str, Any]] = {
    5: {"angle": 0.12, "velocity": 0.0, "torque": 0.1, "temperature": 30.0,
        "mode_status": "CSP", "fault_status": "OK"},
    6: {"angle": -0.05, "velocity": 0.0, "torque": 0.0, "temperature": 29.0,
        "mode_status": "CSP", "fault_status": "OK"},
    7: {"angle": 0.08, "velocity": 0.0, "torque": 0.2, "temperature": 31.0,
        "mode_status": "CSP", "fault_status": "OK"},
    8: {"angle": 0.0, "velocity": 0.0, "torque": 0.0, "temperature": 28.0,
        "mode_status": "CSP", "fault_status": "OK"},
}

UM_STATE: Dict[int, Dict[str, Any]] = {
    1: {"velocity_rpm": 0.0, "current_a": 0.0, "motor_temp_c": 35.0, "alarm_code": 0},
    2: {"velocity_rpm": 0.0, "current_a": 0.0, "motor_temp_c": 34.0, "alarm_code": 0},
    3: {"velocity_rpm": 0.0, "current_a": 0.0, "motor_temp_c": 36.0, "alarm_code": 0},
    4: {"velocity_rpm": 0.0, "current_a": 0.0, "motor_temp_c": 33.0, "alarm_code": 0},
}

CALL_LOG: List[Tuple[str, Any]] = []


class MockBus:
    channel = "can5"

    def shutdown(self):
        CALL_LOG.append(("bus.shutdown", None))


MOCK_BUS = MockBus()


def _log(name: str, detail: Any = None):
    CALL_LOG.append((name, detail))


def mock_verify_can(up: bool = True):
    def _fn(interface, log=None):
        _log("verify_can_interface", interface)
        return up
    return _fn


def mock_get_motor_status_readonly(bus, motor_id, **kwargs):
    _log("get_motor_status_readonly", motor_id)
    info = RS_STATE.get(motor_id, {}).copy()
    return (0, info) if info else (1, None)


def mock_enable_motor(bus, motor_id, **kwargs):
    _log("enable_motor", motor_id)
    return 0


def mock_disable_motor(bus, motor_id, **kwargs):
    _log("disable_motor", motor_id)
    return 0


def mock_set_control_mode(bus, motor_id, mode="csp", **kwargs):
    _log("set_control_mode", (motor_id, mode))
    return 0


def mock_csp_set_speed_limits(bus, motor_id, **kwargs):
    _log("csp_set_speed_limits", motor_id)
    return 0


def mock_csp_motion_control(bus, motor_id, position, **kwargs):
    _log("csp_motion_control", (motor_id, position))
    if motor_id in RS_STATE and position is not None:
        RS_STATE[motor_id]["angle"] = float(position)
    return 0


def mock_set_zero_sta_parameter(bus, motor_id, zero_sta, **kwargs):
    _log("set_zero_sta_parameter", (motor_id, zero_sta))
    return 0


def mock_set_motor_zero(bus, motor_id, **kwargs):
    _log("set_motor_zero", motor_id)
    if motor_id in RS_STATE:
        RS_STATE[motor_id]["angle"] = 0.0
    return 0


def mock_auto_calibrate_zero(bus, motor_id, **kwargs):
    _log("auto_calibrate_zero", motor_id)
    if motor_id in RS_STATE:
        RS_STATE[motor_id]["angle"] = 0.0
    return True, 0.0, 0.5, -0.5


def mock_configure_um_motor_tpdo(can, node_id, **kwargs):
    _log("configure_um_motor_tpdo", (can, node_id))
    return True


def mock_enable_um_motor(can, node_id, **kwargs):
    _log("enable_um_motor", (can, node_id))
    return True


def mock_disable_um_motor(can, node_id, **kwargs):
    _log("disable_um_motor", (can, node_id))
    return True


def mock_stop_um_motor(can, node_id, **kwargs):
    _log("stop_um_motor", (can, node_id))
    if node_id in UM_STATE:
        UM_STATE[node_id]["velocity_rpm"] = 0.0
    return True


def mock_set_um_motor_speed_rpm(can, node_id, speed_rpm, **kwargs):
    _log("set_um_motor_speed_rpm", (can, node_id, speed_rpm))
    if node_id in UM_STATE:
        UM_STATE[node_id]["velocity_rpm"] = float(speed_rpm)
    return True


def mock_read_um_motor_pdo(can, node_id, **kwargs):
    _log("read_um_motor_pdo", (can, node_id))
    st = UM_STATE.get(node_id, {})
    rpm = st.get("velocity_rpm", 0.0)
    return {"velocity_rpm": rpm}


def mock_parse_um_motor_pdo(pdo, **kwargs):
    return {"velocity_rpm": pdo.get("velocity_rpm", 0.0)}


def mock_read_um_motor_status(can, node_id, **kwargs):
    _log("read_um_motor_status", (can, node_id))
    return UM_STATE.get(node_id, {}).copy()


def mock_scan_um_motors(can, **kwargs):
    _log("scan_um_motors", can)
    return list(UM_STATE.keys())


PATCHES = [
    patch(
        "can.interface.Bus",
        side_effect=lambda **kw: (_log("can.interface.Bus", kw.get("channel")), MOCK_BUS)[1],
    ),
    patch("can.Bus", side_effect=lambda **kw: (_log("can.Bus", kw.get("channel")), MOCK_BUS)[1]),
    patch("openflex_driver._lib.can_utils.verify_can_interface", mock_verify_can(True)),
    patch("openflex_driver.chassis.get_motor_status_readonly", mock_get_motor_status_readonly),
    patch("openflex_driver.chassis.enable_motor", mock_enable_motor),
    patch("openflex_driver.chassis.disable_motor", mock_disable_motor),
    patch("openflex_driver.chassis.set_control_mode", mock_set_control_mode),
    patch("openflex_driver.chassis.set_motor_zero", mock_set_motor_zero),
    patch("openflex_driver.chassis.set_zero_sta_parameter", mock_set_zero_sta_parameter),
    patch("openflex_driver.chassis.csp_set_speed_limits", mock_csp_set_speed_limits),
    patch("openflex_driver.chassis.csp_motion_control", mock_csp_motion_control),
    patch("openflex_driver.chassis.auto_calibrate_zero", mock_auto_calibrate_zero),
    patch("openflex_driver.chassis.configure_um_motor_tpdo", mock_configure_um_motor_tpdo),
    patch("openflex_driver.chassis.enable_um_motor", mock_enable_um_motor),
    patch("openflex_driver.chassis.disable_um_motor", mock_disable_um_motor),
    patch("openflex_driver.chassis.stop_um_motor", mock_stop_um_motor),
    patch("openflex_driver.chassis.set_um_motor_speed_rpm", mock_set_um_motor_speed_rpm),
    patch("openflex_driver.chassis.read_um_motor_pdo", mock_read_um_motor_pdo),
    patch("openflex_driver.chassis.parse_um_motor_pdo", mock_parse_um_motor_pdo),
    patch("openflex_driver.chassis.read_um_motor_status", mock_read_um_motor_status),
    patch("openflex_driver.chassis.scan_um_motors", mock_scan_um_motors),
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
            res.detail = f"缺少底层调用: {missing}; 实际: {actual}"
        else:
            res.ok = True
            res.detail = f"底层调用: {actual}"
        res.calls = actual
    except Exception as exc:
        res.detail = f"异常: {exc}\n{traceback.format_exc()}"
    return res


def main() -> int:
    results: List[TestResult] = []
    for p in PATCHES:
        p.start()

    try:
        chassis = Chassis(steering_can="can5", driving_can="can4", log=lambda *a, **k: None)

        # ---- 连接底盘 ----
        results.append(run_case(
            "连接底盘",
            lambda: chassis.connect(),
            ["can.interface.Bus"],
        ))

        # ---- 扫描电机 ----
        def t_scan():
            r = chassis.scan_motors()
            assert set(r["steering"]) == {5, 6, 7, 8}
            assert set(r["driving"]) == {1, 2, 3, 4}

        results.append(run_case("扫描电机", t_scan, ["get_motor_status_readonly", "scan_um_motors"]))

        # ---- 使能全部 ----
        results.append(run_case(
            "使能全部(8电机)",
            lambda: chassis.enable_all_motors(),
            ["set_control_mode", "enable_motor", "enable_um_motor"],
        ))

        # ---- RS 单电机：使能 / 设角 / 回零 / 手动设零 / 自动设零 / 失能 ----
        module = "FL"
        cfg = chassis.modules[module]

        results.append(run_case(
            f"RS {module} 使能",
            lambda: chassis.enable_steering_motor(cfg.steering_id),
            ["set_control_mode", "csp_motion_control", "enable_motor"],
        ))

        def t_rs_angle():
            RS_STATE[cfg.steering_id]["angle"] = 0.0
            chassis.set_steering_angle_deg(module, 15.0)
            assert abs(RS_STATE[cfg.steering_id]["angle"]) > 0.01

        results.append(run_case(
            f"RS {module} 设置角度",
            t_rs_angle,
            ["csp_motion_control"],
        ))

        results.append(run_case(
            f"RS {module} 回零(运动到0°)",
            lambda: chassis.go_steering_home([module]),
            ["csp_motion_control"],
        ))

        RS_STATE[cfg.steering_id]["angle"] = 0.2

        results.append(run_case(
            f"RS {module} 手动设零",
            lambda: chassis.set_steering_zero_manual([module]),
            ["disable_motor", "set_zero_sta_parameter", "set_motor_zero"],
        ))

        RS_STATE[cfg.steering_id]["angle"] = 0.3

        results.append(run_case(
            f"RS {module} 自动设零",
            lambda: chassis.set_steering_zero_auto([module]),
            ["auto_calibrate_zero"],
        ))

        results.append(run_case(
            f"RS {module} 失能",
            lambda: chassis.disable_steering_motor(cfg.steering_id),
            ["disable_motor"],
        ))

        # ---- UM 单电机：使能 / 启动(设速) / 改速 / 停止 / 失能 ----
        um_mod = "FR"
        um_cfg = chassis.modules[um_mod]

        results.append(run_case(
            f"UM {um_mod} 使能",
            lambda: chassis.enable_driving_motor(um_cfg.driving_id),
            ["configure_um_motor_tpdo", "enable_um_motor"],
        ))

        def t_um_start():
            chassis.set_driving_speed_rpm(um_mod, 50.0)
            assert UM_STATE[um_cfg.driving_id]["velocity_rpm"] == 50.0 * um_cfg.driving_direction

        results.append(run_case(
            f"UM {um_mod} 启动(设速50RPM)",
            t_um_start,
            ["set_um_motor_speed_rpm"],
        ))

        def t_um_update():
            chassis.set_driving_speed_rpm(um_mod, 80.0)
            assert UM_STATE[um_cfg.driving_id]["velocity_rpm"] == 80.0 * um_cfg.driving_direction

        results.append(run_case(
            f"UM {um_mod} 实时改速(80RPM)",
            t_um_update,
            ["set_um_motor_speed_rpm"],
        ))

        results.append(run_case(
            f"UM {um_mod} 停止",
            lambda: chassis.stop_module_driving(um_mod),
            ["stop_um_motor"],
        ))

        results.append(run_case(
            f"UM {um_mod} 失能",
            lambda: chassis.disable_driving_motor(um_cfg.driving_id),
            ["stop_um_motor", "disable_um_motor"],
        ))

        # ---- 全局：停止全部驱动 / 失能全部 / 刷新状态 / 断开 ----
        results.append(run_case(
            "停止全部UM驱动",
            lambda: chassis.stop_all_driving(),
            ["stop_um_motor"],
        ))

        results.append(run_case(
            "失能全部",
            lambda: chassis.disable_all_motors(),
            ["disable_um_motor", "disable_motor"],
        ))

        def t_status():
            chassis.refresh_status()
            table = chassis.get_status_table()
            assert len(table) == 8

        results.append(run_case(
            "刷新状态/监控",
            t_status,
            ["get_motor_status_readonly", "read_um_motor_status"],
        ))

        results.append(run_case(
            "断开底盘",
            lambda: chassis.close(),
            ["disable_um_motor", "disable_motor", "bus.shutdown"],
        ))

    finally:
        for p in PATCHES:
            p.stop()

    # ---- 报告 ----
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print("=" * 72)
    print(f"底盘 Mock CAN 测试: {passed}/{total} 通过")
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
