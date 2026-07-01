#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底盘模块全按钮 Mock 测试（无真实 CAN）。

通过 ChassisController + 模拟 UI 控件，逐一触发底盘页所有按钮逻辑并验证底层调用。
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Any, Callable, List, Optional
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QWidget,
)

CHASSIS_SPEED_SLIDER_SCALE = 100

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from openflex_driver.chassis import MODULE_NAMES  # noqa: E402
from utils.settings import SettingsManager  # noqa: E402

# 同目录 mock 模块（scripts 非 package，按文件路径加载）
import importlib.util

_MOCK_PATH = os.path.join(os.path.dirname(__file__), "test_chassis_mock.py")
_spec = importlib.util.spec_from_file_location("test_chassis_mock", _MOCK_PATH)
_mock = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mock)
CALL_LOG = _mock.CALL_LOG
PATCHES = _mock.PATCHES
RS_STATE = _mock.RS_STATE
UM_STATE = _mock.UM_STATE


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 8000, step_ms: int = 30) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(step_ms / 1000.0)
    return False


def wait_thread_idle(ctrl: Any, attr: str, timeout_ms: int = 8000) -> bool:
    """等待后台 QThread 启动并完成（attr 不存在时先等待其出现）。"""

    def _done() -> bool:
        if not hasattr(ctrl, attr):
            return False
        thread = getattr(ctrl, attr)
        if thread is None:
            return True
        return not thread.isRunning()

    ok = wait_until(_done, timeout_ms)
    if ok:
        QApplication.processEvents()
    return ok


class MockStack:
    def __init__(self):
        self._index = 0

    def setCurrentIndex(self, index: int):
        self._index = index

    def currentIndex(self) -> int:
        return self._index


class MockWindow(QWidget):
    """模拟底盘页 UI 控件（ChassisController 所需最小集合）。"""

    def __init__(self):
        super().__init__()
        self.logs: List[str] = []
        self.chassis_table = QTableWidget(0, 8)
        self.chassis_um_controls = {}
        self.chassis_rs_controls = {}

        self.slider_chassis_linear_speed = QSlider()
        self.slider_chassis_linear_speed.setRange(0, 200)
        self.slider_chassis_linear_speed.setValue(20)
        self.slider_chassis_angular_speed = QSlider()
        self.slider_chassis_angular_speed.setRange(0, 300)
        self.slider_chassis_angular_speed.setValue(50)

        self._build_motion_buttons()
        self._build_module_controls()
        self._build_view_switch()

        self.connect_text = ""

    def _build_motion_buttons(self):
        for name in (
            "forward", "backward", "left", "right", "rotate_left", "rotate_right",
        ):
            btn = QPushButton()
            btn.setCheckable(True)
            setattr(self, f"btn_chassis_{name}", btn)
        self.btn_chassis_motion_stop = QPushButton()

    def _build_module_controls(self):
        for module in MODULE_NAMES:
            um_spin = QDoubleSpinBox()
            um_spin.setRange(-330.0, 330.0)
            um_spin.setValue(30.0)
            self.chassis_um_controls[module] = {
                "btn_enable": QPushButton(),
                "btn_disable": QPushButton(),
                "btn_start": QPushButton(),
                "btn_stop": QPushButton(),
                "spin_speed": um_spin,
            }
            rs_spin = QDoubleSpinBox()
            rs_spin.setRange(-90.0, 90.0)
            rs_spin.setValue(10.0)
            self.chassis_rs_controls[module] = {
                "btn_enable": QPushButton(),
                "btn_disable": QPushButton(),
                "btn_zero_manual": QPushButton(),
                "btn_zero_auto": QPushButton(),
                "btn_go_zero": QPushButton(),
                "btn_apply_angle": QPushButton(),
                "spin_angle": rs_spin,
            }

    def _build_view_switch(self):
        self._chassis_control_view = "motion"
        self.chassis_control_stack = MockStack()
        self.chassis_control_stack.setCurrentIndex(1)
        self.btn_chassis_switch_view = QPushButton()
        self.btn_chassis_switch_view.clicked.connect(self._toggle_chassis_control_view)

    def _toggle_chassis_control_view(self):
        if self._chassis_control_view == "motor":
            self._chassis_control_view = "motion"
            self.chassis_control_stack.setCurrentIndex(1)
        else:
            self._chassis_control_view = "motor"
            self.chassis_control_stack.setCurrentIndex(0)

    def apply_chassis_speed_slider_limits(
        self,
        max_linear_m_s: float,
        max_angular_rad_s: float,
    ) -> None:
        max_lin = max(1, int(round(max_linear_m_s * CHASSIS_SPEED_SLIDER_SCALE)))
        max_ang = max(1, int(round(max_angular_rad_s * CHASSIS_SPEED_SLIDER_SCALE)))
        self.slider_chassis_linear_speed.setRange(0, max_lin)
        self.slider_chassis_angular_speed.setRange(0, max_ang)

    def get_chassis_linear_speed_m_s(self) -> float:
        return self.slider_chassis_linear_speed.value() / CHASSIS_SPEED_SLIDER_SCALE

    def get_chassis_angular_speed_rad_s(self) -> float:
        return self.slider_chassis_angular_speed.value() / CHASSIS_SPEED_SLIDER_SCALE

    def _update_chassis_connect_button_text(self):
        self.connect_text = "connected"

    def apply_chassis_um_speed_limits(self, _max_rpm: float):
        pass

    def apply_chassis_rs_angle_limits(self, _max_deg: float):
        pass

    def retranslate_ui(self):
        pass


class MockMain:
    def __init__(self, window: MockWindow):
        self.window = window
        self.settings = SettingsManager()
        self.robot = None

    def log(self, message: str, level: str = "INFO"):
        self.window.logs.append(f"[{level}] {message}")


def _calls_since(start: int) -> List[str]:
    return [name for name, _ in CALL_LOG[start:]]


def run_case(name: str, fn: Callable[[], None], check: Optional[Callable[[], None]] = None) -> TestResult:
    res = TestResult(name)
    try:
        fn()
        if check is not None:
            check()
        res.ok = True
        res.detail = "OK"
    except Exception as exc:
        res.detail = f"{exc}\n{traceback.format_exc()}"
    return res


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)

    results: List[TestResult] = []
    for p in PATCHES:
        p.start()

    # 必须在 patch 生效后再导入，否则 controller 内 verify_can_interface 仍是真函数
    ctrl_verify_patch = patch(
        "controllers.chassis_controller.verify_can_interface",
        _mock.mock_verify_can(True),
    )
    ctrl_verify_patch.start()
    from controllers.chassis_controller import ChassisController  # noqa: E402

    try:
        window = MockWindow()
        main = MockMain(window)
        ctrl = ChassisController(main)

        # ---- 界面切换按钮 ----
        def t_switch_view():
            assert window._chassis_control_view == "motion"
            assert window.chassis_control_stack.currentIndex() == 1
            window.btn_chassis_switch_view.click()
            assert window._chassis_control_view == "motor"
            assert window.chassis_control_stack.currentIndex() == 0
            window.btn_chassis_switch_view.click()
            assert window._chassis_control_view == "motion"
            assert window.chassis_control_stack.currentIndex() == 1

        results.append(run_case("界面切换按钮", t_switch_view))

        # ---- 连接底盘 ----
        def t_connect():
            start = len(CALL_LOG)
            ctrl.connect()
            assert wait_thread_idle(ctrl, "_connect_thread"), "连接线程超时"
            assert ctrl.is_connected, "连接后 is_connected 应为 True"
            calls = _calls_since(start)
            assert "can.interface.Bus" in calls

        results.append(run_case("连接底盘", t_connect))

        # ---- 扫描电机 ----
        def t_scan():
            start = len(CALL_LOG)
            ctrl.scan_motors()
            assert wait_thread_idle(ctrl, "_scan_thread"), "扫描线程超时"
            calls = _calls_since(start)
            assert "scan_um_motors" in calls
            assert "get_motor_status_readonly" in calls

        results.append(run_case("扫描电机", t_scan))

        # ---- RS 单控：未「使能全部」时设角（rebuild bus + 自动使能）----
        def t_rs_apply_without_bulk_enable():
            mod = "FL"
            assert mod not in ctrl._rs_steering_enabled
            ctrl.window.chassis_rs_controls[mod]["spin_angle"].setValue(15.0)
            start = len(CALL_LOG)
            ctrl.apply_steering_angle(mod)
            calls = _calls_since(start)
            assert "can.interface.Bus" in calls, "设角前应 rebuild RS CAN 总线"
            assert "set_control_mode" in calls, "设角前应自动使能 RS"
            assert "csp_motion_control" in calls
            assert mod in ctrl._rs_steering_enabled

        results.append(run_case("RS(FL) 未使能全部时可设角", t_rs_apply_without_bulk_enable))

        # ---- UM 单控：未「使能全部」时启动（自动使能 + 设速）----
        def t_um_start_without_bulk_enable():
            mod = "FR"
            cfg = ctrl.chassis.modules[mod]
            assert mod not in ctrl._um_driving_enabled
            ctrl.window.chassis_um_controls[mod]["spin_speed"].setValue(40.0)
            start = len(CALL_LOG)
            ctrl.start_driving_motor(mod)
            calls = _calls_since(start)
            assert "enable_um_motor" in calls, "启动前应自动使能 UM"
            assert "set_um_motor_speed_rpm" in calls
            assert mod in ctrl._um_driving_enabled
            assert UM_STATE[cfg.driving_id]["velocity_rpm"] != 0.0
            ctrl.stop_driving_motor(mod)

        results.append(run_case("UM(FR) 未使能全部时可启动", t_um_start_without_bulk_enable))

        # ---- 使能全部 ----
        def t_enable_all():
            start = len(CALL_LOG)
            ctrl.enable_all()
            assert ctrl.chassis.is_enabled, "底盘未标记为已使能"
            calls = _calls_since(start)
            assert "enable_motor" in calls
            assert "enable_um_motor" in calls

        results.append(run_case("使能全部", t_enable_all))

        # ---- UM 单电机：FL 使能/启动/停止/失能 ----
        def t_um_fl():
            mod = "FL"
            cfg = ctrl.chassis.modules[mod]
            start = len(CALL_LOG)
            ctrl.enable_driving_motor(mod)
            calls = _calls_since(start)
            assert "enable_um_motor" in calls

            start = len(CALL_LOG)
            ctrl.start_driving_motor(mod)
            calls = _calls_since(start)
            assert "set_um_motor_speed_rpm" in calls
            assert UM_STATE[cfg.driving_id]["velocity_rpm"] != 0.0

            start = len(CALL_LOG)
            ctrl.stop_driving_motor(mod)
            calls = _calls_since(start)
            assert "stop_um_motor" in calls

            start = len(CALL_LOG)
            ctrl.disable_driving_motor(mod)
            calls = _calls_since(start)
            assert "disable_um_motor" in calls

        results.append(run_case("UM(FL) 使能/启动/停止/失能", t_um_fl))

        # ---- UM 其余三轮冒烟 ----
        for mod in ("FR", "BL", "BR"):
            def _um_smoke(m=mod):
                ctrl.enable_driving_motor(m)
                ctrl.start_driving_motor(m)
                ctrl.stop_driving_motor(m)

            results.append(run_case(f"UM({mod}) 启动/停止", _um_smoke))

        # ---- RS 单电机：FL 使能/设角/手动设零/回零/自动设零/失能 ----
        def t_rs_fl():
            mod = "FL"
            cfg = ctrl.chassis.modules[mod]
            start = len(CALL_LOG)
            ctrl.enable_steering_motor(mod)
            calls = _calls_since(start)
            assert "enable_motor" in calls

            start = len(CALL_LOG)
            ctrl.apply_steering_angle(mod)
            calls = _calls_since(start)
            assert "csp_motion_control" in calls

            RS_STATE[cfg.steering_id]["angle"] = 0.2
            start = len(CALL_LOG)
            ctrl.set_steering_zero_manual(modules=[mod])
            assert wait_thread_idle(ctrl, "_zero_thread"), "手动设零线程超时"
            calls = _calls_since(start)
            assert "set_motor_zero" in calls

            start = len(CALL_LOG)
            ctrl.go_steering_home(modules=[mod])
            assert wait_thread_idle(ctrl, "_go_home_thread"), "回零线程超时"
            calls = _calls_since(start)
            assert "csp_motion_control" in calls

            RS_STATE[cfg.steering_id]["angle"] = 0.3
            start = len(CALL_LOG)
            ctrl.set_steering_zero_auto(modules=[mod])
            assert wait_thread_idle(ctrl, "_zero_thread"), "自动设零线程超时"
            calls = _calls_since(start)
            assert "auto_calibrate_zero" in calls

            # 自动设零后底层会失能，需重新使能 RS
            ctrl.enable_steering_motor(mod)
            start = len(CALL_LOG)
            ctrl.disable_steering_motor(mod)
            calls = _calls_since(start)
            assert "disable_motor" in calls

        results.append(run_case("RS(FL) 使能/设角/设零/回零/失能", t_rs_fl))

        # ---- RS 其余三轮冒烟 ----
        for mod in ("FR", "BL", "BR"):
            def _rs_smoke(m=mod):
                ctrl.enable_steering_motor(m)
                ctrl.apply_steering_angle(m)

            results.append(run_case(f"RS({mod}) 使能/设角", _rs_smoke))

        # ---- 重新使能全部（运动控制前置条件）----
        def t_reenable():
            ctrl.enable_all()
            assert ctrl.chassis.is_enabled

        results.append(run_case("重新使能全部", t_reenable))

        # ---- 整车运动按钮 ----
        motion_cases = [
            ("前进", "forward", lambda: ctrl._on_motion_button_clicked("forward", "drive", "backward")),
            ("后退", "backward", lambda: ctrl._on_motion_button_clicked("backward", "drive", "forward")),
            ("向左", "left", lambda: ctrl._on_motion_button_clicked("left", "strafe", "right")),
            ("向右", "right", lambda: ctrl._on_motion_button_clicked("right", "strafe", "left")),
            ("左转", "rotate_left", lambda: ctrl._on_motion_button_clicked("rotate_left", "turn", "rotate_right")),
            ("右转", "rotate_right", lambda: ctrl._on_motion_button_clicked("rotate_right", "turn", "rotate_left")),
        ]
        for label, mode, handler in motion_cases:
            def _motion(start_calls=len(CALL_LOG), h=handler, m=mode):
                h()
                QApplication.processEvents()
                calls = _calls_since(start_calls)
                assert "csp_motion_control" in calls, f"{m} 未下发 RS"
                assert "set_um_motor_speed_rpm" in calls, f"{m} 未下发 UM"
                assert ctrl._motion_repeat_timer.isActive(), f"{m} 重复下发定时器未启动"
                # 再次点击取消该方向
                h()
                QApplication.processEvents()

            results.append(run_case(f"运动按钮-{label}", _motion))

        def t_motion_speed_change():
            ctrl._on_motion_button_clicked("forward", "drive", "backward")
            start = len(CALL_LOG)
            window.slider_chassis_linear_speed.setValue(35)
            QApplication.processEvents()
            calls = _calls_since(start)
            assert "set_um_motor_speed_rpm" in calls

        results.append(run_case("运动中修改线速度", t_motion_speed_change))

        def t_motion_stop():
            start = len(CALL_LOG)
            ctrl._on_motion_stop_clicked()
            calls = _calls_since(start)
            assert "stop_um_motor" in calls
            assert not ctrl._motion_repeat_timer.isActive()
            assert ctrl._drive_direction is None

        results.append(run_case("运动停止按钮", t_motion_stop))

        # ---- 停止驱动（工具栏）----
        def t_stop_all():
            ctrl.start_driving_motor("FL")
            start = len(CALL_LOG)
            ctrl.stop_chassis_movement()
            calls = _calls_since(start)
            assert "stop_um_motor" in calls

        results.append(run_case("停止驱动(工具栏)", t_stop_all))

        # ---- 状态监控开关 ----
        def t_monitor_toggle():
            ctrl.start_monitoring(interval_ms=100)
            assert ctrl.is_monitoring
            ctrl.stop_monitoring()
            assert not ctrl.is_monitoring

        results.append(run_case("状态监控开/关", t_monitor_toggle))

        # ---- 失能全部 ----
        def t_disable_all():
            start = len(CALL_LOG)
            ctrl.disable_all()
            assert wait_thread_idle(ctrl, "_disable_thread"), "失能线程超时"
            calls = _calls_since(start)
            assert "disable_um_motor" in calls
            assert "disable_motor" in calls
            assert not ctrl.chassis.is_enabled

        results.append(run_case("失能全部", t_disable_all))

        # ---- 急停 ----
        def t_estop():
            ctrl.enable_all()
            assert ctrl.chassis.is_enabled
            ctrl._on_motion_button_clicked("forward", "drive", "backward")
            start = len(CALL_LOG)
            ctrl.emergency_stop()
            assert wait_thread_idle(ctrl, "_disable_thread"), "急停失能线程超时"
            calls = _calls_since(start)
            assert "stop_um_motor" in calls
            assert not ctrl._motion_repeat_timer.isActive()
            assert not ctrl.chassis.is_enabled

        results.append(run_case("急停", t_estop))

        # ---- 断开底盘 ----
        def t_disconnect():
            if not ctrl.is_connected:
                ctrl.connect()
                assert wait_thread_idle(ctrl, "_connect_thread")
            start = len(CALL_LOG)
            ctrl.disconnect()
            assert not ctrl.is_connected
            calls = _calls_since(start)
            assert "bus.shutdown" in calls

        results.append(run_case("断开底盘", t_disconnect))

        # ---- 连接/断开切换（连接按钮 toggle）----
        def t_toggle_connect():
            ctrl.toggle_connect()
            assert wait_thread_idle(ctrl, "_connect_thread")
            assert ctrl.is_connected
            ctrl.toggle_connect()
            assert not ctrl.is_connected

        results.append(run_case("连接按钮(切换连接/断开)", t_toggle_connect))

    finally:
        ctrl_verify_patch.stop()
        for p in reversed(PATCHES):
            p.stop()

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print("=" * 72)
    print(f"底盘全按钮 Mock 测试: {passed}/{total} 通过")
    print("=" * 72)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"[{mark}] {r.name}")
        if not r.ok:
            print(f"       {r.detail.splitlines()[0]}")
    print("=" * 72)
    if passed < total:
        print("\n失败详情:")
        for r in results:
            if not r.ok:
                print(f"\n--- {r.name} ---\n{r.detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
