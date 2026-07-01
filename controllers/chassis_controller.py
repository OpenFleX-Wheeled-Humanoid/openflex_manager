#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
底盘控制器 — 整车运动与 RS 回零

4 × 灵足 RS 转向电机 (can5, ID 5-8, CSP)
4 × UM10540 轮毂电机 (can4, Node 1-4, CANopen PV)

整车前进/后退/原地旋转由 Chassis 逆运动学封装；UI 仅保留运动按钮与被动/主动回零。
"""

import math
import time
from typing import Dict, List, Optional, Union

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import QProgressDialog

from openflex_driver.chassis import (
    Chassis,
    DEFAULT_MODULES,
    MODULE_NAMES,
    MODULE_NAMES_CN,
    WheelModuleConfig,
)
from openflex_driver._lib.can_utils import verify_can_interface
from utils.i18n import t
from controllers.arm_controller import translate_motor_status


class ChassisConnectThread(QThread):
    """后台连接 CAN 总线。"""

    finished_signal = Signal(bool, str)

    def __init__(self, chassis: Chassis):
        super().__init__()
        self.chassis = chassis

    def run(self):
        try:
            if not verify_can_interface(self.chassis.steering_can):
                self.finished_signal.emit(
                    False,
                    f"CAN 接口 {self.chassis.steering_can} 未启动",
                )
                return
            if not verify_can_interface(self.chassis.driving_can):
                self.finished_signal.emit(
                    False,
                    f"CAN 接口 {self.chassis.driving_can} 未启动",
                )
                return
            self.chassis.connect()
            self.finished_signal.emit(True, "")
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


class ChassisEnableThread(QThread):
    """后台使能全部底盘电机。"""

    finished_signal = Signal(dict, list)

    def __init__(self, chassis: Chassis):
        super().__init__()
        self.chassis = chassis

    def run(self):
        failed = []
        results = {}
        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                results = self.chassis.enable_all_motors(verbose=False)
                for name in MODULE_NAMES:
                    cfg = self.chassis.modules[name]
                    if results.get(cfg.steering_id, 1) != 0:
                        failed.append({
                            "module": name,
                            "name_cn": MODULE_NAMES_CN[name],
                            "motor_type": "RS",
                            "can_channel": self.chassis.steering_can,
                            "motor_id": cfg.steering_id,
                            "error": "使能失败",
                        })
                    if results.get(cfg.driving_id, 1) != 0:
                        failed.append({
                            "module": name,
                            "name_cn": MODULE_NAMES_CN[name],
                            "motor_type": "UM",
                            "can_channel": self.chassis.driving_can,
                            "motor_id": cfg.driving_id,
                            "error": "使能失败",
                        })
                self.finished_signal.emit(results, failed)
                return
            except Exception as exc:
                err = str(exc)
                if ("网络已关闭" in err or "Network is down" in err or
                        "Failed to transmit" in err):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                self.finished_signal.emit({}, [{
                    "module": "系统",
                    "name_cn": "底盘",
                    "motor_type": "-",
                    "can_channel": "-",
                    "motor_id": -1,
                    "error": err,
                }])
                return


class ChassisDisableThread(QThread):
    """后台失能全部底盘电机。"""

    finished_signal = Signal(dict, list)

    def __init__(self, chassis: Chassis):
        super().__init__()
        self.chassis = chassis

    def run(self):
        try:
            results = self.chassis.disable_all_motors(verbose=False)
            failed = []
            for name in MODULE_NAMES:
                cfg = self.chassis.modules[name]
                if results.get(cfg.steering_id, 1) != 0:
                    failed.append({
                        "module": name,
                        "name_cn": MODULE_NAMES_CN[name],
                        "motor_type": "RS",
                        "can_channel": self.chassis.steering_can,
                        "motor_id": cfg.steering_id,
                        "error": "失能失败",
                    })
                if results.get(cfg.driving_id, 1) != 0:
                    failed.append({
                        "module": name,
                        "name_cn": MODULE_NAMES_CN[name],
                        "motor_type": "UM",
                        "can_channel": self.chassis.driving_can,
                        "motor_id": cfg.driving_id,
                        "error": "失能失败",
                    })
            self.finished_signal.emit(results, failed)
        except Exception as exc:
            self.finished_signal.emit({}, [{
                "module": "系统",
                "name_cn": "底盘",
                "motor_type": "-",
                "can_channel": "-",
                "motor_id": -1,
                "error": str(exc),
            }])


class ChassisScanThread(QThread):
    """后台扫描 8 个电机在线状态。"""

    finished_signal = Signal(dict)

    def __init__(self, chassis: Chassis):
        super().__init__()
        self.chassis = chassis

    def run(self):
        try:
            if not self.chassis.is_connected:
                self.chassis.connect()
            self.chassis.ensure_steering_bus()
            result = self.chassis.scan_motors()
            self.finished_signal.emit(result)
        except Exception as exc:
            self.finished_signal.emit({"error": str(exc)})


class ChassisStatusThread(QThread):
    """后台读取完整状态。"""

    finished_signal = Signal(dict)

    def __init__(self, chassis: Chassis):
        super().__init__()
        self.chassis = chassis

    def run(self):
        try:
            self.chassis.ensure_steering_bus()
            self.chassis.refresh_status()
            status = self.chassis.get_status()
            self.finished_signal.emit(status)
        except Exception as exc:
            self.finished_signal.emit({"error": str(exc)})


class ChassisSetZeroThread(QThread):
    """后台 RS 转向设零（手动 / 自动）。"""

    finished_signal = Signal(dict)

    def __init__(
        self,
        chassis: Chassis,
        modules: Optional[List[str]] = None,
        mode: str = "manual",
        zero_pos_per: Optional[float] = None,
    ):
        super().__init__()
        self.chassis = chassis
        self.modules = modules
        self.mode = mode
        self.zero_pos_per = zero_pos_per

    def run(self):
        try:
            self.chassis.ensure_steering_bus()
            if self.mode in ("active", "auto"):
                results = self.chassis.set_steering_zero_auto(
                    modules=self.modules,
                    zero_pos_per=self.zero_pos_per,
                )
            else:
                results = self.chassis.set_steering_zero_manual(modules=self.modules)
            self.finished_signal.emit(results)
        except Exception as exc:
            self.finished_signal.emit({"error": str(exc)})


class ChassisGoHomeThread(QThread):
    """后台 RS 转向回零（运动到逻辑 0°）。"""

    finished_signal = Signal(dict)

    def __init__(self, chassis: Chassis, modules: Optional[List[str]] = None):
        super().__init__()
        self.chassis = chassis
        self.modules = modules

    def run(self):
        try:
            self.chassis.ensure_steering_bus()
            results = self.chassis.go_steering_home(modules=self.modules)
            self.finished_signal.emit(results)
        except Exception as exc:
            self.finished_signal.emit({"error": str(exc)})


class ChassisController:
    """
    底盘底层控制器

    管理 Chassis 实例，提供 connect/enable/disable/scan/运动控制/状态监控 API。
  UI 层通过本控制器访问硬件，不直接操作 CAN。
    """

    def __init__(self, main_controller):
        self.main = main_controller
        self.window = main_controller.window
        self.settings = main_controller.settings
        self.log = main_controller.log
        self.chassis: Optional[Chassis] = None

        self._connected = False
        self._last_status: Optional[dict] = None
        self._monitor_timer = QTimer()
        self._monitor_timer.timeout.connect(self._on_monitor_tick)
        self.is_monitoring = False
        self._um_driving_active: set[str] = set()
        self._um_driving_enabled: set[str] = set()
        self._rs_steering_enabled: set[str] = set()

        self._init_chassis()
        self._init_motion_state()
        self._wire_signals()

    def _init_chassis(self):
        """从配置创建 Chassis 实例。"""
        steering_can = self.settings.get("steering_can", "can5")
        driving_can = self.settings.get("driving_can", "can4")

        modules = dict(DEFAULT_MODULES)
        for name in MODULE_NAMES:
            prefix = f"chassis_{name.lower()}_"
            steering_id = self.settings.get(f"{prefix}steering_id")
            driving_id = self.settings.get(f"{prefix}driving_id")
            driving_dir = self.settings.get(f"{prefix}driving_direction")
            zero_offset = self.settings.get(f"{prefix}zero_offset")
            if any(v is not None for v in (steering_id, driving_id, driving_dir, zero_offset)):
                base = modules[name]
                modules[name] = WheelModuleConfig(
                    name=name,
                    steering_id=steering_id if steering_id is not None else base.steering_id,
                    driving_id=driving_id if driving_id is not None else base.driving_id,
                    driving_direction=driving_dir if driving_dir is not None else base.driving_direction,
                    steering_direction=base.steering_direction,
                    steering_zero_offset_rad=zero_offset if zero_offset is not None else base.steering_zero_offset_rad,
                )

        self.chassis = Chassis(
            steering_can=steering_can,
            driving_can=driving_can,
            modules=modules,
            steering_angle_limit_rad=math.radians(
                float(self.settings.get("chassis_steering_angle_limit_deg", 90.0))
            ),
            steering_speed_limit=float(self.settings.get("chassis_steering_speed_limit", 10.0)),
            steering_current_limit=float(self.settings.get("chassis_steering_current_limit", 8.0)),
            driving_max_speed_rpm=float(self.settings.get("chassis_driving_max_speed_rpm", 330.0)),
            driving_profile_accel_ms=int(self.settings.get("chassis_driving_profile_accel_ms", 1000)),
            driving_profile_decel_ms=int(self.settings.get("chassis_driving_profile_decel_ms", 1000)),
            driving_can_watchdog_timeout_ms=int(self.settings.get("chassis_can_watchdog_timeout_ms", 100)),
            driving_can_watchdog_action=int(self.settings.get("chassis_can_watchdog_action", 2)),
            driving_tpdo_period_ms=int(self.settings.get("chassis_tpdo_period_ms", 20)),
            active_zero_torque=float(self.settings.get("chassis_active_zero_torque", 1.5)),
            active_zero_velocity=float(self.settings.get("chassis_active_zero_velocity", 0.3)),
            active_zero_pos_per=float(self.settings.get("chassis_active_zero_pos_per", 0.5)),
            active_zero_max_duration=float(self.settings.get("chassis_active_zero_max_duration", 20.0)),
            wheel_radius=float(self.settings.get("chassis_wheel_radius", 0.075)),
            wheelbase=float(self.settings.get("chassis_wheelbase", 0.42)),
            track_width=float(self.settings.get("chassis_track_width", 0.547)),
            log=self.log,
        )

        self._apply_motor_spinbox_limits()
        self._apply_speed_spinbox_limits()

        linear = float(self.settings.get("chassis_default_linear_speed_m_s", 0.2))
        angular = float(self.settings.get("chassis_default_angular_speed_rad_s", 0.5))
        if hasattr(self.window, "set_chassis_linear_speed_m_s"):
            self.window.set_chassis_linear_speed_m_s(linear)
            self.window.set_chassis_angular_speed_rad_s(angular)

    def _init_motion_state(self):
        """初始化整车运动状态。"""
        self._drive_direction: Optional[str] = None
        self._strafe_direction: Optional[str] = None
        self._turn_direction: Optional[str] = None
        self._motion_repeat_timer = QTimer()
        self._motion_repeat_timer.timeout.connect(self._on_motion_repeat)
        self._um_driving_repeat_timer = QTimer()
        self._um_driving_repeat_timer.timeout.connect(self._on_um_driving_repeat)
        self._um_driving_repeat_ms = max(
            20,
            min(
                80,
                int(self.settings.get("chassis_um_keepalive_ms", 50)),
            ),
        )

    def _start_um_driving_repeat(self) -> None:
        if not self._um_driving_active:
            return
        if not self._um_driving_repeat_timer.isActive():
            self._um_driving_repeat_timer.start(self._um_driving_repeat_ms)

    def _stop_um_driving_repeat(self) -> None:
        self._um_driving_repeat_timer.stop()

    def _on_um_driving_repeat(self) -> None:
        """周期重发 UM 目标转速，避免 CAN 看门狗清零速度。"""
        if not self._um_driving_active:
            self._stop_um_driving_repeat()
            return
        if not self.is_connected or not self.chassis:
            self._um_driving_active.clear()
            self._stop_um_driving_repeat()
            return
        for name in list(self._um_driving_active):
            try:
                speed_rpm = self._um_target_speed(name)
                if abs(speed_rpm) < 0.01:
                    continue
                self.chassis.set_driving_speed_rpm(name, speed_rpm)
            except Exception as exc:
                self._um_driving_active.discard(name)
                self.log(f"UM({name}) 速度维持失败: {exc}", "ERROR")
        if not self._um_driving_active:
            self._stop_um_driving_repeat()

    def _apply_speed_spinbox_limits(self):
        """按底层硬件上限设置线速度/角速度滑条范围。"""
        if not self.chassis:
            return
        w = self.window
        if not hasattr(w, "slider_chassis_linear_speed"):
            return
        max_lin = self.chassis.max_linear_speed_m_s
        max_ang = self.chassis.max_angular_speed_rad_s
        w.apply_chassis_speed_slider_limits(max_lin, max_ang)

    def _apply_motor_spinbox_limits(self):
        """按硬件上限设置单电机速度/角度输入范围。"""
        if not self.chassis:
            return
        w = self.window
        if hasattr(w, "apply_chassis_um_speed_limits"):
            w.apply_chassis_um_speed_limits(self.chassis.driving_max_speed_rpm)
        if hasattr(w, "apply_chassis_rs_angle_limits"):
            max_deg = math.degrees(self.chassis.steering_angle_limit_rad)
            w.apply_chassis_rs_angle_limits(max_deg)

    def _wire_signals(self):
        """连接 UI 信号。"""
        w = self.window
        signal_map = [
            ("btn_chassis_connect", self.toggle_connect),
            ("btn_chassis_enable", self.enable_all),
            ("btn_chassis_disable", self.disable_all),
            ("btn_chassis_scan", self.scan_motors),
            ("btn_chassis_stop", self.stop_chassis_movement),
            ("btn_chassis_estop", self.emergency_stop),
            ("btn_chassis_toggle_monitor", self.toggle_monitoring),
        ]
        for attr, handler in signal_map:
            widget = getattr(w, attr, None)
            if widget is not None:
                widget.clicked.connect(handler)

        motion_buttons = [
            ("btn_chassis_forward", "forward", "drive", "backward"),
            ("btn_chassis_backward", "backward", "drive", "forward"),
            ("btn_chassis_left", "left", "strafe", "right"),
            ("btn_chassis_right", "right", "strafe", "left"),
            ("btn_chassis_rotate_left", "rotate_left", "turn", "rotate_right"),
            ("btn_chassis_rotate_right", "rotate_right", "turn", "rotate_left"),
        ]
        for btn_name, mode, axis, opposite in motion_buttons:
            btn = getattr(w, btn_name, None)
            if btn is None:
                continue
            btn.clicked.connect(
                lambda _checked=False, m=mode, a=axis, o=opposite: self._on_motion_button_clicked(m, a, o)
            )

        motion_stop = getattr(w, "btn_chassis_motion_stop", None)
        if motion_stop is not None:
            motion_stop.clicked.connect(self._on_motion_stop_clicked)

        if hasattr(w, "slider_chassis_linear_speed"):
            w.slider_chassis_linear_speed.valueChanged.connect(self._on_motion_speed_changed)
        if hasattr(w, "slider_chassis_angular_speed"):
            w.slider_chassis_angular_speed.valueChanged.connect(self._on_motion_speed_changed)

        for module, ctrl in getattr(w, "chassis_um_controls", {}).items():
            ctrl["btn_enable"].clicked.connect(
                lambda _=False, m=module: self.enable_driving_motor(m)
            )
            ctrl["btn_disable"].clicked.connect(
                lambda _=False, m=module: self.disable_driving_motor(m)
            )
            ctrl["btn_start"].clicked.connect(
                lambda _=False, m=module: self.start_driving_motor(m)
            )
            ctrl["btn_stop"].clicked.connect(
                lambda _=False, m=module: self.stop_driving_motor(m)
            )
            ctrl["spin_speed"].valueChanged.connect(
                lambda _v, m=module: self._on_um_speed_value_changed(m)
            )

        for module, ctrl in getattr(w, "chassis_rs_controls", {}).items():
            ctrl["btn_enable"].clicked.connect(
                lambda _=False, m=module: self.enable_steering_motor(m)
            )
            ctrl["btn_disable"].clicked.connect(
                lambda _=False, m=module: self.disable_steering_motor(m)
            )
            ctrl["btn_zero_manual"].clicked.connect(
                lambda _=False, m=module: self.set_steering_zero_manual(modules=[m])
            )
            ctrl["btn_zero_auto"].clicked.connect(
                lambda _=False, m=module: self.set_steering_zero_auto(modules=[m])
            )
            ctrl["btn_go_zero"].clicked.connect(
                lambda _=False, m=module: self.go_steering_home(modules=[m])
            )
            ctrl["btn_apply_angle"].clicked.connect(
                lambda _=False, m=module: self.apply_steering_angle(m)
            )
            ctrl["spin_angle"].editingFinished.connect(
                lambda m=module: self.apply_steering_angle(m)
            )

    # ==================== 连接管理 ====================

    def _prepare_steering_bus(self) -> None:
        """在当前线程重建 RS CAN 总线（避免 connect 子线程与 UI 主线程跨线程）。"""
        if self.chassis and self.chassis.is_connected:
            self.chassis.ensure_steering_bus()

    def _ensure_connected(self) -> bool:
        """若未连接则尝试同步连接 CAN。"""
        if self.is_connected:
            return True
        if not self.chassis:
            return False
        if not verify_can_interface(self.chassis.steering_can):
            self.log(f"CAN 接口 {self.chassis.steering_can} 未启动", "ERROR")
            return False
        if not verify_can_interface(self.chassis.driving_can):
            self.log(f"CAN 接口 {self.chassis.driving_can} 未启动", "ERROR")
            return False
        try:
            self.chassis.connect()
            self._prepare_steering_bus()
            self._connected = True
            if self.main.robot:
                self.main.robot.chassis = self.chassis
            self.window._update_chassis_connect_button_text()
            self._apply_motor_spinbox_limits()
            self._apply_speed_spinbox_limits()
            if hasattr(self.window, "retranslate_ui"):
                self.window.retranslate_ui()
            return True
        except Exception as exc:
            self.log(f"底盘连接失败: {exc}", "ERROR")
            return False

    def connect(self):
        """连接底盘 CAN（can5 + can4）。"""
        if not self.chassis:
            self.log("Chassis 未初始化", "ERROR")
            return

        self.log(
            f"连接底盘: 转向={self.chassis.steering_can} 驱动={self.chassis.driving_can}",
            "INFO",
        )
        self._connect_thread = ChassisConnectThread(self.chassis)
        self._connect_thread.finished_signal.connect(self._on_connect_finished)
        self._connect_thread.start()

    def _on_connect_finished(self, ok: bool, error: str):
        if ok:
            self._prepare_steering_bus()
            self._connected = True
            self.log(
                f"底盘已连接: {self.chassis.steering_can} / {self.chassis.driving_can}",
                "SUCCESS",
            )
            if self.main.robot:
                self.main.robot.chassis = self.chassis
            self.window._update_chassis_connect_button_text()
            self._apply_motor_spinbox_limits()
            self._apply_speed_spinbox_limits()
        else:
            self.log(f"底盘连接失败: {error}", "ERROR")

    def disconnect(self):
        """断开底盘连接。"""
        self.stop_monitoring()
        if self.chassis and self.chassis.is_connected:
            try:
                self.chassis.close()
            except Exception as exc:
                self.log(f"底盘断开异常: {exc}", "WARNING")
        self._connected = False
        self._last_status = None
        self._rs_steering_enabled.clear()
        self._um_driving_enabled.clear()
        self._um_driving_active.clear()
        self.log("底盘已断开", "INFO")
        self.window._update_chassis_connect_button_text()

    def toggle_connect(self):
        if self.is_connected:
            self.disconnect()
        else:
            self.connect()

    @property
    def is_connected(self) -> bool:
        """以 Chassis 实例为准（与 Robot 共用实例时状态一致）。"""
        return self.chassis is not None and self.chassis.is_connected

    def _require_connected(self):
        if not self.is_connected:
            raise RuntimeError("底盘未连接，请先连接 CAN")

    def _ensure_enabled(self) -> bool:
        """运动下发前检查底盘是否已使能。"""
        if not self.chassis or not self.chassis.is_enabled:
            self.log("请先使能底盘电机", "ERROR")
            return False
        return True

    def _module_cfg(self, module: str):
        name = module.upper()
        if name not in MODULE_NAMES:
            raise ValueError(f"无效模块: {module}")
        return self.chassis.modules[name]

    # ==================== 使能 / 失能 ====================

    def _enable_all_motors_sync(self) -> tuple:
        """主线程同步使能全部底盘电机。"""
        failed = []
        results = {}
        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                self.chassis.ensure_steering_bus()
                results = self.chassis.enable_all_motors(verbose=False)
                for name in MODULE_NAMES:
                    cfg = self.chassis.modules[name]
                    if results.get(cfg.steering_id, 1) != 0:
                        failed.append({
                            "module": name,
                            "name_cn": MODULE_NAMES_CN[name],
                            "motor_type": "RS",
                            "can_channel": self.chassis.steering_can,
                            "motor_id": cfg.steering_id,
                            "error": "使能失败",
                        })
                    if results.get(cfg.driving_id, 1) != 0:
                        failed.append({
                            "module": name,
                            "name_cn": MODULE_NAMES_CN[name],
                            "motor_type": "UM",
                            "can_channel": self.chassis.driving_can,
                            "motor_id": cfg.driving_id,
                            "error": "使能失败",
                        })
                return results, failed
            except Exception as exc:
                failed = []
                err = str(exc)
                if ("网络已关闭" in err or "Network is down" in err or
                        "Failed to transmit" in err):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                return {}, [{
                    "module": "系统",
                    "name_cn": "底盘",
                    "motor_type": "-",
                    "can_channel": "-",
                    "motor_id": -1,
                    "error": err,
                }]
        return results, failed

    def enable_all(self):
        """使能全部 8 个电机（4 RS + 4 UM）。"""
        if not self.chassis:
            self.log("Chassis 未初始化", "ERROR")
            return
        if not self._ensure_connected():
            return

        self.log("使能底盘全部电机...", "INFO")
        self._enable_progress = QProgressDialog(
            t("dialog_chassis_enabling"),
            "",
            0, 0,
            self.window,
        )
        self._enable_progress.setWindowTitle(t("dialog_chassis_enabling_title"))
        self._enable_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._enable_progress.setCancelButton(None)
        self._enable_progress.setMinimumDuration(0)
        self._enable_progress.show()

        try:
            results, failed = self._enable_all_motors_sync()
        except Exception as exc:
            results, failed = {}, [{
                "module": "系统",
                "name_cn": "底盘",
                "motor_type": "-",
                "can_channel": "-",
                "motor_id": -1,
                "error": str(exc),
            }]
        finally:
            if hasattr(self, "_enable_progress"):
                self._enable_progress.close()
                delattr(self, "_enable_progress")

        self._on_enable_finished(results, failed)

    def _on_enable_finished(self, results: dict, failed: list):
        if hasattr(self, "_enable_progress"):
            self._enable_progress.close()
            delattr(self, "_enable_progress")
        ok_count = sum(1 for v in results.values() if v == 0)
        total = len(results)
        if ok_count == total and total > 0:
            self._rs_steering_enabled = set(MODULE_NAMES)
            self._um_driving_enabled = set(MODULE_NAMES)
            self._set_motor_mode_display("Motor mode")
            self.log(f"底盘使能成功: {ok_count}/{total} 个电机", "SUCCESS")
        elif ok_count > 0:
            self.log(f"底盘部分使能: {ok_count}/{total} 成功", "WARNING")
        else:
            self.log("底盘使能失败", "ERROR")
        if failed:
            for item in failed:
                self.log(
                    f"  [{item['name_cn']}] {item['motor_type']}"
                    f" ID={item['motor_id']} @ {item['can_channel']}: {item['error']}",
                    "ERROR",
                )

    def disable_all(self):
        """失能全部底盘电机。"""
        if not self.chassis:
            return
        self.log("失能底盘全部电机...", "INFO")
        self._disable_progress = QProgressDialog(
            t("dialog_chassis_disabling"),
            "",
            0, 0,
            self.window,
        )
        self._disable_progress.setWindowTitle(t("dialog_chassis_disabling_title"))
        self._disable_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._disable_progress.setCancelButton(None)
        self._disable_progress.setMinimumDuration(0)
        self._disable_progress.show()

        self._disable_thread = ChassisDisableThread(self.chassis)
        self._disable_thread.finished_signal.connect(self._on_disable_finished)
        self._disable_thread.start()

    def _on_disable_finished(self, results: dict, failed: list):
        if hasattr(self, "_disable_progress"):
            self._disable_progress.close()
            delattr(self, "_disable_progress")
        ok_count = sum(1 for v in results.values() if v == 0)
        self.log(f"底盘已失能: {ok_count}/{len(results)} 成功", "INFO")
        self._rs_steering_enabled.clear()
        self._um_driving_enabled.clear()
        self._um_driving_active.clear()
        self._set_motor_mode_display("Reset mode")
        if failed:
            for item in failed:
                self.log(
                    f"  [{item['name_cn']}] {item['motor_type']}"
                    f" ID={item['motor_id']}: {item['error']}",
                    "WARNING",
                )
        else:
            self.disconnect()

    def enable_module(self, module: str):
        """使能单个模块（1 RS + 1 UM）。"""
        self._require_connected()
        name = module.upper()
        self.log(f"使能模块 {name}({MODULE_NAMES_CN.get(name, name)})...", "INFO")
        try:
            self.chassis.enable_module(name)
            self.log(f"模块 {name} 使能成功", "SUCCESS")
        except Exception as exc:
            self.log(f"模块 {name} 使能失败: {exc}", "ERROR")

    def disable_module(self, module: str):
        """失能单个模块。"""
        if not self.chassis or not self.is_connected:
            return
        name = module.upper()
        self.chassis.disable_module(name)
        self.log(f"模块 {name} 已失能", "INFO")

    def _ensure_um_driving_ready(self, module: str) -> bool:
        """确保 UM 驱动已使能（未使能时自动走 PV 使能流程）。"""
        if not self._ensure_connected():
            return False
        name = module.upper()
        if name in self._um_driving_enabled:
            return True
        cfg = self._module_cfg(name)
        self.log(
            f"UM 驱动 {name}({MODULE_NAMES_CN.get(name, name)}) 未使能，自动使能...",
            "INFO",
        )
        try:
            ok = self.chassis.enable_driving_motor(cfg.driving_id)
            if not ok:
                self.log(f"UM Node {cfg.driving_id} 自动使能失败", "ERROR")
                return False
            self._um_driving_enabled.add(name)
            return True
        except Exception as exc:
            self.log(f"UM Node {cfg.driving_id} 自动使能异常: {exc}", "ERROR")
            return False

    def enable_driving_motor(self, module: str):
        """使能单个 UM 驱动电机。"""
        if not self._ensure_connected():
            return
        name = module.upper()
        cfg = self._module_cfg(name)
        self.log(
            f"使能 UM 驱动 {name}({MODULE_NAMES_CN.get(name, name)}) Node {cfg.driving_id}...",
            "INFO",
        )
        try:
            ok = self.chassis.enable_driving_motor(cfg.driving_id)
            if ok:
                self._um_driving_enabled.add(name)
                self.log(f"UM Node {cfg.driving_id} 使能成功", "SUCCESS")
            else:
                self.log(f"UM Node {cfg.driving_id} 使能失败", "ERROR")
        except Exception as exc:
            self.log(f"UM Node {cfg.driving_id} 使能异常: {exc}", "ERROR")

    def disable_driving_motor(self, module: str):
        """失能单个 UM 驱动电机。"""
        if not self.chassis or not self.is_connected:
            return
        name = module.upper()
        cfg = self._module_cfg(name)
        self._um_driving_active.discard(name)
        self._um_driving_enabled.discard(name)
        try:
            ok = self.chassis.disable_driving_motor(cfg.driving_id)
            self.chassis.stop_module_driving(name)
            if ok:
                self.log(f"UM Node {cfg.driving_id} 已失能", "INFO")
            else:
                self.log(f"UM Node {cfg.driving_id} 失能失败", "WARNING")
        except Exception as exc:
            self.log(f"UM Node {cfg.driving_id} 失能异常: {exc}", "ERROR")

    def _on_um_speed_value_changed(self, module: str):
        """运行中实时跟随输入框更新目标转速。"""
        name = module.upper()
        if name not in self._um_driving_active:
            return
        try:
            self._send_driving_speed(name, log=False)
        except Exception as exc:
            self.log(f"UM 速度更新失败: {exc}", "ERROR")

    def start_driving_motor(self, module: str):
        """启动单个 UM 驱动：按当前输入转速运行，之后改输入会实时更新。"""
        if not self._ensure_connected():
            return
        name = module.upper()
        cfg = self._module_cfg(name)
        speed_rpm = self._um_target_speed(name)
        if abs(speed_rpm) < 0.01:
            self.log(
                f"[{MODULE_NAMES_CN.get(name, name)}] UM 转速为 0，请先设置转速再点启动",
                "WARNING",
            )
            return
        min_rpm = float(self.settings.get("chassis_um_min_start_rpm", 15.0))
        if abs(speed_rpm) < min_rpm:
            self.log(
                f"[{MODULE_NAMES_CN.get(name, name)}] UM 转速 {speed_rpm:+.1f} RPM 过低，"
                f"建议 ≥ {min_rpm:.0f} RPM 才能明显转动",
                "WARNING",
            )
        if not self._ensure_um_driving_ready(name):
            return
        current_rpm = self.chassis.read_module_driving_speed_rpm(name)
        self._um_driving_active.add(name)
        try:
            self._send_driving_speed(name, log=False)
            self._start_um_driving_repeat()
            if current_rpm is not None:
                self.log(
                    f"[{MODULE_NAMES_CN.get(name, name)}] UM({cfg.driving_id}) "
                    f"{current_rpm:+.1f} → {speed_rpm:+.1f} RPM",
                    "SUCCESS",
                )
            else:
                self.log(
                    f"[{MODULE_NAMES_CN.get(name, name)}] UM({cfg.driving_id}) "
                    f"已启动，转速={speed_rpm:+.1f} RPM",
                    "SUCCESS",
                )
        except Exception as exc:
            self._um_driving_active.discard(name)
            if not self._um_driving_active:
                self._stop_um_driving_repeat()
            self.log(f"UM 启动失败: {exc}", "ERROR")

    def stop_driving_motor(self, module: str):
        """停止单个 UM 驱动（速度归零，保留输入框目标值）。"""
        if not self.chassis or not self.is_connected:
            return
        name = module.upper()
        cfg = self._module_cfg(name)
        self._um_driving_active.discard(name)
        if not self._um_driving_active:
            self._stop_um_driving_repeat()
        try:
            self.chassis.stop_module_driving(name)
            self.log(
                f"[{MODULE_NAMES_CN.get(name, name)}] UM({cfg.driving_id}) 已停止",
                "INFO",
            )
        except Exception as exc:
            self.log(f"UM 停止失败: {exc}", "ERROR")

    def _um_target_speed(self, module: str) -> float:
        ctrl = self.window.chassis_um_controls.get(module.upper())
        if not ctrl:
            return 0.0
        return float(ctrl["spin_speed"].value())

    def _send_driving_speed(self, module: str, log: bool = True):
        if not self._ensure_connected():
            return
        name = module.upper()
        if not self._ensure_um_driving_ready(name):
            raise RuntimeError(f"UM({self._module_cfg(name).driving_id}) 未使能")
        speed_rpm = self._um_target_speed(name)
        self.chassis.set_driving_speed_rpm(name, speed_rpm)
        if log:
            self.log(
                f"[{MODULE_NAMES_CN.get(name, name)}] UM({self._module_cfg(name).driving_id}) "
                f"速度={speed_rpm:+.1f} RPM",
                "SUCCESS",
            )

    def apply_driving_speed(self, module: str):
        """编程接口：单次下发目标速度（不进入持续运行状态）。"""
        if not self._ensure_connected():
            return
        try:
            self._send_driving_speed(module.upper(), log=True)
        except Exception as exc:
            self.log(f"UM 速度下发失败: {exc}", "ERROR")

    def _ensure_rs_steering_ready(self, module: str) -> bool:
        """确保 RS 转向已在当前线程就绪（重建 bus + 必要时自动使能）。"""
        if not self._ensure_connected():
            return False
        self._prepare_steering_bus()
        name = module.upper()
        if name in self._rs_steering_enabled:
            return True
        cfg = self._module_cfg(name)
        self.log(
            f"RS 转向 {name}({MODULE_NAMES_CN.get(name, name)}) 未使能，自动使能...",
            "INFO",
        )
        try:
            state = self.chassis.enable_steering_motor(cfg.steering_id)
            if state != 0:
                self.log(f"RS ID {cfg.steering_id} 自动使能失败, state={state}", "ERROR")
                return False
            self._rs_steering_enabled.add(name)
            return True
        except Exception as exc:
            self.log(f"RS ID {cfg.steering_id} 自动使能异常: {exc}", "ERROR")
            return False

    def enable_steering_motor(self, module: str):
        """使能单个 RS 转向电机。"""
        if not self._ensure_connected():
            return
        self._prepare_steering_bus()
        name = module.upper()
        cfg = self._module_cfg(name)
        self.log(
            f"使能 RS 转向 {name}({MODULE_NAMES_CN.get(name, name)}) ID {cfg.steering_id}...",
            "INFO",
        )
        try:
            state = self.chassis.enable_steering_motor(cfg.steering_id)
            if state == 0:
                self._rs_steering_enabled.add(name)
                self.log(f"RS ID {cfg.steering_id} 使能成功", "SUCCESS")
            else:
                self.log(f"RS ID {cfg.steering_id} 使能失败, state={state}", "ERROR")
        except Exception as exc:
            self.log(f"RS ID {cfg.steering_id} 使能异常: {exc}", "ERROR")

    def disable_steering_motor(self, module: str):
        """失能单个 RS 转向电机。"""
        if not self.chassis or not self.is_connected:
            return
        self._prepare_steering_bus()
        name = module.upper()
        cfg = self._module_cfg(name)
        try:
            state = self.chassis.disable_steering_motor(cfg.steering_id)
            self._rs_steering_enabled.discard(name)
            if state == 0:
                self.log(f"RS ID {cfg.steering_id} 已失能", "INFO")
            else:
                self.log(f"RS ID {cfg.steering_id} 失能失败", "WARNING")
        except Exception as exc:
            self.log(f"RS ID {cfg.steering_id} 失能异常: {exc}", "ERROR")

    def apply_steering_angle(self, module: str):
        """下发单个 RS 转向目标角度 (°)，从当前位置移动到设定值。"""
        name = module.upper()
        ctrl = self.window.chassis_rs_controls.get(name)
        if not ctrl:
            return
        if not self._ensure_rs_steering_ready(name):
            return
        angle_deg = float(ctrl["spin_angle"].value())
        current_deg = self.chassis.read_module_steering_angle_deg(name)
        try:
            self.chassis.set_steering_angle_deg(name, angle_deg)
            if current_deg is not None:
                self.log(
                    f"[{MODULE_NAMES_CN.get(name, name)}] RS({self._module_cfg(name).steering_id}) "
                    f"{current_deg:+.1f}° → {angle_deg:+.1f}°",
                    "SUCCESS",
                )
            else:
                self.log(
                    f"[{MODULE_NAMES_CN.get(name, name)}] RS({self._module_cfg(name).steering_id}) "
                    f"目标角度={angle_deg:+.1f}°",
                    "SUCCESS",
                )
        except Exception as exc:
            self.log(f"RS 角度下发失败: {exc}", "ERROR")

    # ==================== 运动控制（单电机 API，保留供编程调用） ====================

    def set_module_command(self, module: str, angle_deg: float, speed_rpm: float):
        """
        下发单模块命令。

        参数:
            module: FL/FR/BL/BR
            angle_deg: 转向角度（度），零点 ±90°
            speed_rpm: 驱动速度（RPM）
        """
        self._require_connected()
        name = module.upper()
        self.chassis.set_module_command_deg(name, angle_deg, speed_rpm)
        self.log(
            f"[{name}] 角度={angle_deg:+.1f}° 速度={speed_rpm:+.0f} RPM",
            "INFO",
        )

    def set_steering_angle_deg(self, module: str, angle_deg: float):
        self._require_connected()
        self.chassis.set_steering_angle_deg(module.upper(), angle_deg)

    def set_driving_speed_rpm(self, module: str, speed_rpm: float):
        self._require_connected()
        self.chassis.set_driving_speed_rpm(module.upper(), speed_rpm)

    def set_all_modules(self, angle_deg: float, speed_rpm: float):
        """全局下发：4 个模块相同角度和速度。"""
        self._require_connected()
        for name in MODULE_NAMES:
            self.chassis.set_module_command_deg(name, angle_deg, speed_rpm)
        self.log(
            f"全部模块下发: 角度={angle_deg:+.1f}° 速度={speed_rpm:+.0f} RPM",
            "INFO",
        )

    def stop_motion(self):
        """停止整车运动（四轮轮毂速度归零）。"""
        self._motion_repeat_timer.stop()
        self._clear_motion_button_states()
        if self.chassis and self.is_connected:
            self.chassis.stop_motion()
            self.log("整车运动已停止", "WARNING")

    def _on_motion_stop_clicked(self):
        self.stop_motion()

    def _clear_motion_button_states(self):
        self._drive_direction = None
        self._strafe_direction = None
        self._turn_direction = None
        for name in (
            "btn_chassis_forward",
            "btn_chassis_backward",
            "btn_chassis_left",
            "btn_chassis_right",
            "btn_chassis_rotate_left",
            "btn_chassis_rotate_right",
        ):
            btn = getattr(self.window, name, None)
            if btn is not None:
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)

    def stop_all_driving(self):
        """四个 UM 驱动速度归零。"""
        self._um_driving_active.clear()
        self._stop_um_driving_repeat()
        if self.chassis and self.is_connected:
            self.chassis.stop_all_driving()
            for ctrl in getattr(self.window, "chassis_um_controls", {}).values():
                spin = ctrl.get("spin_speed")
                if spin is not None:
                    spin.blockSignals(True)
                    spin.setValue(0.0)
                    spin.blockSignals(False)
            self.log("全部 UM 驱动速度已置零", "WARNING")

    def stop_chassis_movement(self):
        """停止底盘全部运动（单电机驱动 + 整车运动）。"""
        self.stop_motion()
        self.stop_all_driving()

    def stop_module_driving(self, module: str):
        name = module.upper()
        self._um_driving_active.discard(name)
        if self.chassis and self.is_connected:
            self.chassis.stop_module_driving(name)

    def emergency_stop(self):
        """急停：先停全部 UM 速度，再失能全部电机。"""
        self.log("底盘急停!", "ERROR")
        self._um_driving_active.clear()
        self._stop_um_driving_repeat()
        self._motion_repeat_timer.stop()
        self._clear_motion_button_states()
        try:
            if self.chassis and self.is_connected:
                self.chassis.stop_motion()
        finally:
            self.disable_all()

    # ==================== 整车运动 ====================

    def _compute_motion_velocity(self) -> tuple:
        """根据当前选中方向与输入幅值计算 vx / vy / omega。"""
        linear = self.window.get_chassis_linear_speed_m_s()
        angular = self.window.get_chassis_angular_speed_rad_s()
        vx = 0.0
        vy = 0.0
        omega = 0.0
        if self._drive_direction == "forward":
            vx = linear
        elif self._drive_direction == "backward":
            vx = -linear
        if self._strafe_direction == "left":
            vy = linear
        elif self._strafe_direction == "right":
            vy = -linear
        if self._turn_direction == "rotate_left":
            omega = angular
        elif self._turn_direction == "rotate_right":
            omega = -angular
        return vx, vy, omega

    def _sync_chassis_motion(self, log_stop: bool = False):
        """按当前按钮组合下发 vx + vy + omega，支持复合运动。"""
        vx, vy, omega = self._compute_motion_velocity()
        if abs(vx) < 1e-6 and abs(vy) < 1e-6 and abs(omega) < 1e-6:
            self._motion_repeat_timer.stop()
            if self.chassis and self.is_connected:
                self.chassis.stop_motion()
            if log_stop:
                self.log("底盘运动已停止", "INFO")
            return
        if not self._ensure_connected():
            self.log("请先连接底盘", "ERROR")
            self._clear_motion_button_states()
            return
        if not self._ensure_enabled():
            self._clear_motion_button_states()
            return
        try:
            self.chassis.set_chassis_velocity(vx, vy, omega)
            if not self._motion_repeat_timer.isActive():
                self._motion_repeat_timer.start(self._um_driving_repeat_ms)
        except Exception as exc:
            self._motion_repeat_timer.stop()
            self._clear_motion_button_states()
            self.log(f"底盘运动下发失败: {exc}", "ERROR")

    def _on_motion_button_clicked(self, mode: str, axis: str, opposite: str):
        if axis == "drive":
            state_attr = "_drive_direction"
        elif axis == "strafe":
            state_attr = "_strafe_direction"
        else:
            state_attr = "_turn_direction"
        current = getattr(self, state_attr)
        btn = getattr(self.window, f"btn_chassis_{mode}", None)
        opp_btn = getattr(self.window, f"btn_chassis_{opposite}", None)

        if current == mode:
            setattr(self, state_attr, None)
            if btn is not None:
                btn.setChecked(False)
        else:
            setattr(self, state_attr, mode)
            if btn is not None:
                btn.setChecked(True)
            if opp_btn is not None:
                opp_btn.blockSignals(True)
                opp_btn.setChecked(False)
                opp_btn.blockSignals(False)

        self._sync_chassis_motion()

    def _on_motion_speed_changed(self, _value: float = 0.0):
        if self._drive_direction or self._strafe_direction or self._turn_direction:
            self._sync_chassis_motion()

    def _on_motion_repeat(self):
        if not (self._drive_direction or self._strafe_direction or self._turn_direction):
            self._motion_repeat_timer.stop()
            return
        if not self.is_connected or not self.chassis:
            self._motion_repeat_timer.stop()
            self._clear_motion_button_states()
            return
        if not self.chassis.is_enabled:
            self._motion_repeat_timer.stop()
            self._clear_motion_button_states()
            self.log("底盘已失能，运动已停止", "WARNING")
            return
        try:
            vx, vy, omega = self._compute_motion_velocity()
            self.chassis.set_chassis_velocity(vx, vy, omega)
        except Exception as exc:
            self.log(f"底盘运动维持失败: {exc}", "ERROR")
            self.stop_motion()

    # ==================== 设零 / 回零 / 扫描 ====================

    def _normalize_modules(
        self, modules: Optional[Union[str, List[str]]]
    ) -> Optional[List[str]]:
        if modules is None:
            return None
        if isinstance(modules, str):
            return [modules.upper()]
        return [m.upper() for m in modules]

    def _module_label(self, module: str) -> str:
        key = f"chassis_module_{module.upper()}"
        label = t(key)
        if label == key:
            return MODULE_NAMES_CN.get(module.upper(), module)
        return label

    def _start_zero_thread(
        self,
        mode: str,
        modules: Optional[Union[str, List[str]]] = None,
        zero_pos_per: Optional[float] = None,
    ):
        if not self.is_connected:
            self.log(t("log_chassis_not_connected"), "ERROR")
            return

        mod_list = self._normalize_modules(modules)
        is_auto = mode in ("active", "auto")
        mode_label = t("btn_chassis_zero_auto") if is_auto else t("btn_chassis_zero_manual")
        mod_hint = ""
        if mod_list and len(mod_list) == 1:
            mod_hint = f" [{self._module_label(mod_list[0])}]"
        self.log(f"{t('log_chassis_set_zero_start')}{mod_hint} ({mode_label})", "INFO")
        if is_auto:
            self.log(t("log_chassis_auto_zero_warning"), "WARNING")

        self._zero_thread = ChassisSetZeroThread(
            self.chassis,
            mod_list,
            mode=mode,
            zero_pos_per=zero_pos_per,
        )
        self._zero_thread.finished_signal.connect(
            lambda r, m=mode: self._on_set_zero_finished(r, m)
        )
        self._zero_thread.start()

    def set_steering_zero_manual(self, modules: Optional[Union[str, List[str]]] = None):
        """手动设零：将 RS 转向当前位置设为机械零点。"""
        self._start_zero_thread("manual", modules=modules)

    def set_steering_zero_auto(
        self,
        modules: Optional[Union[str, List[str]]] = None,
        zero_pos_per: Optional[float] = None,
    ):
        """自动设零：RS 转向寻双限位取中点并写机械零点。"""
        self._start_zero_thread("auto", modules=modules, zero_pos_per=zero_pos_per)

    def set_steering_zero_passive(self, modules: Optional[Union[str, List[str]]] = None):
        """兼容旧名：等同手动设零。"""
        self.set_steering_zero_manual(modules=modules)

    def set_steering_zero_active(
        self,
        modules: Optional[Union[str, List[str]]] = None,
        zero_pos_per: Optional[float] = None,
    ):
        """兼容旧名：等同自动设零。"""
        self.set_steering_zero_auto(modules=modules, zero_pos_per=zero_pos_per)

    def set_steering_zero_hw(self, modules: Optional[Union[str, List[str]]] = None):
        """兼容旧名：等同手动设零。"""
        self.set_steering_zero_manual(modules=modules)

    def go_steering_home(self, modules: Optional[Union[str, List[str]]] = None):
        """回零：RS 转向运动到逻辑零点 (0°)。"""
        if not self.is_connected:
            self.log(t("log_chassis_not_connected"), "ERROR")
            return

        mod_list = self._normalize_modules(modules)
        mod_hint = ""
        if mod_list and len(mod_list) == 1:
            mod_hint = f" [{self._module_label(mod_list[0])}]"
        self.log(f"{t('log_chassis_go_zero_start')}{mod_hint}", "INFO")

        self._go_home_thread = ChassisGoHomeThread(self.chassis, mod_list)
        self._go_home_thread.finished_signal.connect(self._on_go_home_finished)
        self._go_home_thread.start()

    def _on_set_zero_finished(self, results: dict, mode: str = "manual"):
        is_auto = mode in ("active", "auto")
        mode_label = t("btn_chassis_zero_auto") if is_auto else t("btn_chassis_zero_manual")
        if "error" in results:
            self.log(t("log_chassis_set_zero_failed", error=results["error"], mode=mode_label), "ERROR")
            return

        ok = sum(1 for r in results.values() if r.get("success"))
        total = len(results)
        if ok == total:
            self.log(t("log_chassis_set_zero_success", ok=ok, total=total, mode=mode_label), "SUCCESS")
            if is_auto:
                self.log(t("log_chassis_auto_zero_reenable"), "WARNING")
        else:
            self.log(t("log_chassis_set_zero_partial", ok=ok, total=total, mode=mode_label), "WARNING")

        for name, r in results.items():
            pos = r.get("after_pos")
            pos_str = f"{math.degrees(pos):+.2f}°" if pos is not None else "-"
            mark = "✓" if r.get("success") else "✗"
            if r.get("success"):
                self._rs_steering_enabled.discard(name)
            extra = ""
            if is_auto and r.get("pos_limit") is not None:
                extra = (
                    f"  限位=[{math.degrees(r['neg_limit']):+.1f}°"
                    f" ~ {math.degrees(r['pos_limit']):+.1f}°]"
                )
            err = f" ({r['error']})" if r.get("error") and not r.get("success") else ""
            self.log(
                f"  {mark} {name}({r.get('name_cn')}) Motor{r.get('motor_id')} "
                f"pos={pos_str}{extra}{err}",
                "INFO" if r.get("success") else "WARNING",
            )

    def _on_go_home_finished(self, results: dict):
        if "error" in results:
            self.log(t("log_chassis_go_zero_failed", error=results["error"]), "ERROR")
            return

        ok = sum(1 for r in results.values() if r.get("success"))
        total = len(results)
        if ok == total:
            self.log(t("log_chassis_go_zero_success", ok=ok, total=total), "SUCCESS")
        else:
            self.log(t("log_chassis_go_zero_partial", ok=ok, total=total), "WARNING")

        for name, r in results.items():
            deg = r.get("angle_deg")
            deg_str = f"{deg:+.2f}°" if deg is not None else "-"
            mark = "✓" if r.get("success") else "✗"
            err = f" ({r['error']})" if r.get("error") and not r.get("success") else ""
            self.log(
                f"  {mark} {name}({r.get('name_cn')}) Motor{r.get('motor_id')} "
                f"angle={deg_str}{err}",
                "INFO" if r.get("success") else "WARNING",
            )
        if self.is_monitoring:
            self.refresh_status()
    def scan_motors(self):
        """扫描 4 RS + 4 UM 在线状态（无需使能）。"""
        if not self.chassis:
            return

        self.log("扫描底盘电机...", "INFO")
        self._scan_thread = ChassisScanThread(self.chassis)
        self._scan_thread.finished_signal.connect(self._on_scan_finished)
        self._scan_thread.start()

    def _on_scan_finished(self, result: dict):
        if "error" in result:
            self.log(f"扫描失败: {result['error']}", "ERROR")
            return

        rs_ids = result.get("steering", [])
        um_ids = result.get("driving", [])
        self.log(
            f"扫描完成 — RS({self.chassis.steering_can}): {rs_ids or '无'}  "
            f"UM({self.chassis.driving_can}): {um_ids or '无'}",
            "SUCCESS" if (rs_ids and um_ids) else "WARNING",
        )

        expected_rs = [self.chassis.modules[n].steering_id for n in MODULE_NAMES]
        expected_um = [self.chassis.modules[n].driving_id for n in MODULE_NAMES]
        for mid in expected_rs:
            if mid not in rs_ids:
                self.log(f"  RS Motor {mid} 离线", "WARNING")
        for nid in expected_um:
            if nid not in um_ids:
                self.log(f"  UM Node {nid} 离线", "WARNING")

    # ==================== 状态监控 ====================

    def refresh_status(self) -> dict:
        """同步刷新并返回状态。"""
        self._require_connected()
        self._prepare_steering_bus()
        self.chassis.refresh_status()
        self._last_status = self.chassis.get_status()
        return self._last_status

    def fetch_status_async(self):
        """异步读取状态（供 UI 表格刷新）。"""
        if not self.is_connected:
            self.log("底盘未连接", "ERROR")
            return
        self._status_thread = ChassisStatusThread(self.chassis)
        self._status_thread.finished_signal.connect(self._on_status_fetched)
        self._status_thread.start()

    def _on_status_fetched(self, status: dict):
        if "error" in status:
            self.log(f"状态读取失败: {status['error']}", "ERROR")
            return
        self._last_status = status
        self._update_status_table(status)
        self._sync_motor_spinboxes_from_status(status)

    def _logical_steering_angle_rad(self, module: str, motor_rad: float) -> float:
        """RS 原始电机角 → 与下发/输入框一致的逻辑角 (rad)。"""
        cfg = self.chassis.modules[module]
        direction = cfg.steering_direction if cfg.steering_direction else 1
        return (float(motor_rad) - cfg.steering_zero_offset_rad) / direction

    def _um_feedback_speed_rpm(self, module: str, pdo: dict, um: dict) -> Optional[float]:
        """UM 反馈转速：优先 TPDO（已含 direction），否则 SDO 并乘 driving_direction。"""
        if pdo.get("velocity_rpm") is not None:
            return float(pdo["velocity_rpm"])
        if um.get("velocity_rpm") is not None:
            cfg = self.chassis.modules[module]
            return float(um["velocity_rpm"]) * cfg.driving_direction
        return None

    def _format_um_position(self, module: str, pdo: dict, um: dict) -> str:
        """UM 位置：TPDO/SDO 编码器计数 + 逻辑角度。"""
        cfg = self.chassis.modules[module]
        resolution = self.chassis.driving_position_resolution
        if pdo.get("position_rad") is not None:
            deg = math.degrees(float(pdo["position_rad"]))
            raw = pdo.get("position_raw")
            if raw is not None:
                return f"{raw} cnt ({deg:+.1f}°)"
            return f"{deg:+.1f}°"
        raw = um.get("position_raw")
        if raw is not None:
            rad = (
                float(raw) * 2.0 * math.pi / resolution
            ) * cfg.driving_direction
            return f"{raw} cnt ({math.degrees(rad):+.1f}°)"
        return "-"

    def _is_um_operation_enabled(self, um: dict) -> bool:
        status_word = um.get("status_word")
        if status_word is None:
            return False
        try:
            return (int(status_word) & 0x006F) == 0x0027
        except Exception:
            return False

    def _format_um_mode(self, module: str, um: dict) -> str:
        mode_status = um.get("mode_status")
        if mode_status:
            return translate_motor_status(mode_status)
        if self._is_um_operation_enabled(um) or module in self._um_driving_enabled:
            return translate_motor_status("Motor mode")
        if um or module not in self._um_driving_enabled:
            return translate_motor_status("Reset mode")
        return "-"

    def _sync_motor_spinboxes_from_status(self, status: dict):
        """监控刷新时同步单电机输入框显示（只读反馈，不自动下发）。"""
        w = self.window
        for name in MODULE_NAMES:
            if name not in status:
                continue
            st = status[name]
            rs = st.get("steering") or {}
            um = st.get("driving") or {}
            pdo = st.get("driving_pdo") or {}

            um_ctrl = getattr(w, "chassis_um_controls", {}).get(name)
            if um_ctrl and name not in self._um_driving_active:
                speed = self._um_feedback_speed_rpm(name, pdo, um)
                if speed is not None:
                    spin = um_ctrl["spin_speed"]
                    if spin.hasFocus():
                        continue
                    spin.blockSignals(True)
                    spin.setValue(float(speed))
                    spin.blockSignals(False)

            rs_ctrl = getattr(w, "chassis_rs_controls", {}).get(name)
            if rs_ctrl and isinstance(rs.get("angle"), (int, float)) and self.chassis:
                spin = rs_ctrl["spin_angle"]
                if spin.hasFocus():
                    continue
                logical_rad = self._logical_steering_angle_rad(name, float(rs["angle"]))
                spin.blockSignals(True)
                spin.setValue(math.degrees(logical_rad))
                spin.blockSignals(False)

    def _build_chassis_status_rows(self, status: dict) -> List[List[str]]:
        """将 get_status() 结果格式化为与 chassis_headers 对齐的表格行。"""
        rows: List[List[str]] = []
        for name in MODULE_NAMES:
            if name not in status:
                continue
            st = status[name]
            rs = st.get("steering") or {}
            um = st.get("driving") or {}
            pdo = st.get("driving_pdo") or {}
            module_label = f"{name}({MODULE_NAMES_CN.get(name, name)})"

            if isinstance(rs.get("angle"), (int, float)):
                logical_rad = self._logical_steering_angle_rad(name, float(rs["angle"]))
                rs_position = (
                    f"{logical_rad:+.3f} rad ({math.degrees(logical_rad):+.1f}°)"
                )
            else:
                rs_position = "-"

            rows.append([
                module_label,
                t("chassis_motor_type_rs"),
                self.chassis.steering_can,
                str(st["steering_id"]),
                rs_position,
                f"{rs.get('velocity', 0.0):+.2f} rad/s",
                f"{rs.get('torque', 0.0):+.2f} Nm",
                f"{rs.get('temperature', 0.0):.1f}",
                translate_motor_status(rs.get("mode_status", "-")),
                translate_motor_status(rs.get("fault_status", "-")),
            ])

            speed_rpm = self._um_feedback_speed_rpm(name, pdo, um)
            speed_text = f"{speed_rpm:+.1f} RPM" if speed_rpm is not None else "-"
            alarm = um.get("alarm_code")
            um_status = f"0x{alarm:04X}" if alarm is not None else ("离线" if not um else "-")

            rows.append([
                module_label,
                t("chassis_motor_type_um"),
                self.chassis.driving_can,
                str(st["driving_id"]),
                self._format_um_position(name, pdo, um),
                speed_text,
                f"{(um.get('current_a') or 0.0):+.2f} A",
                f"{(um.get('motor_temp_c') or 0.0):.1f}",
                self._format_um_mode(name, um),
                um_status,
            ])
        return rows

    def _set_motor_mode_display(self, mode_status: str) -> None:
        """立即同步底盘电机模式列，避免使能/失能后表格停留在旧模式。"""
        if self._last_status:
            for name in MODULE_NAMES:
                steering = self._last_status.get(name, {}).get("steering")
                if isinstance(steering, dict):
                    steering["mode_status"] = mode_status
                driving = self._last_status.get(name, {}).get("driving")
                if isinstance(driving, dict):
                    driving["mode_status"] = mode_status
                    if mode_status == "Motor mode":
                        self._um_driving_enabled.add(name)
                    elif mode_status == "Reset mode":
                        self._um_driving_enabled.discard(name)
            self._update_status_table(self._last_status)
            return

        table = getattr(self.window, "chassis_table", None)
        if table is None:
            return
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTableWidgetItem

        mode_text = translate_motor_status(mode_status)
        for row_idx in range(table.rowCount()):
            type_item = table.item(row_idx, 1)
            if type_item is None or type_item.text() not in (
                t("chassis_motor_type_rs"),
                t("chassis_motor_type_um"),
            ):
                continue
            item = QTableWidgetItem(mode_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row_idx, 8, item)

    def _update_status_table(self, status: dict):
        """更新 UI 表格（若 chassis_table 存在）。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTableWidgetItem

        table = getattr(self.window, "chassis_table", None)
        if table is None:
            return

        rows = self._build_chassis_status_rows(status)
        table.setRowCount(len(rows))
        for row_idx, cells in enumerate(rows):
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_idx, col, item)

    def toggle_monitoring(self):
        if self.is_monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self, interval_ms: int = 200):
        if not self.is_connected:
            self.log("请先连接底盘", "ERROR")
            return
        self.is_monitoring = True
        self._monitor_timer.start(interval_ms)
        btn = getattr(self.window, "btn_chassis_toggle_monitor", None)
        if btn is not None:
            btn.setText(t("btn_stop_monitor"))
        self.log("底盘状态监控已启动", "INFO")
        self.fetch_status_async()

    def stop_monitoring(self):
        self.is_monitoring = False
        self._monitor_timer.stop()
        btn = getattr(self.window, "btn_chassis_toggle_monitor", None)
        if btn is not None:
            btn.setText(t("btn_start_monitor"))
        self.log("底盘状态监控已停止", "INFO")

    def _on_monitor_tick(self):
        if not self.chassis or not self.is_connected:
            self.stop_monitoring()
            return
        try:
            self._prepare_steering_bus()
            self.chassis.refresh_status()
            self._last_status = self.chassis.get_status()
            self._update_status_table(self._last_status)
            self._sync_motor_spinboxes_from_status(self._last_status)
        except Exception as exc:
            self.log(f"监控刷新失败: {exc}", "ERROR")
            self.stop_monitoring()

    def shutdown(self):
        """应用退出时清理。"""
        self._motion_repeat_timer.stop()
        self._stop_um_driving_repeat()
        self._clear_motion_button_states()
        self.stop_chassis_movement()
        self.stop_monitoring()
        self.disconnect()

    @property
    def last_status(self) -> Optional[dict]:
        return self._last_status
