#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
升降台控制器 — 轮廓位置模式运动 + 回零

对齐 lift_slide_servo_controller / lift_slide_hardware_interface。
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from openflex_driver.column import Column, CONTROL_MODE_POSITION, CONTROL_MODE_VELOCITY
from openflex_driver._lib.can_utils import verify_can_interface
from utils.i18n import t


class ColumnPositionMoveThread(QThread):
    finished_signal = Signal(bool, str, float)

    def __init__(self, column: Column, target_m: float, speed_mps: float):
        super().__init__()
        self.column = column
        self.target_m = target_m
        self.speed_mps = speed_mps

    def run(self):
        try:
            ok = self.column.move_to_user_position(self.target_m, speed_mps=self.speed_mps)
            msg = "" if ok else "位置运动失败"
            self.finished_signal.emit(ok, msg, self.target_m)
        except Exception as exc:
            self.finished_signal.emit(False, str(exc), self.target_m)


class ColumnRelativeMoveThread(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, column: Column, delta_m: float, speed_mps: float):
        super().__init__()
        self.column = column
        self.delta_m = delta_m
        self.speed_mps = speed_mps

    def run(self):
        try:
            ok = self.column.move_relative_m(self.delta_m, speed_mps=self.speed_mps)
            msg = "" if ok else "相对移动失败"
            self.finished_signal.emit(ok, msg)
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


class ColumnConnectThread(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, column: Column):
        super().__init__()
        self.column = column

    def run(self):
        try:
            if not verify_can_interface(self.column.can_interface):
                self.finished_signal.emit(
                    False,
                    f"CAN 接口 {self.column.can_interface} 未启动",
                )
                return
            self.column.connect()
            self.finished_signal.emit(True, "")
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


class ColumnEnableThread(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, column: Column):
        super().__init__()
        self.column = column

    def run(self):
        try:
            ok = self.column.enable()
            self.finished_signal.emit(ok, "" if ok else "使能失败")
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


class ColumnDisableThread(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, column: Column):
        super().__init__()
        self.column = column

    def run(self):
        try:
            ok = self.column.disable()
            self.finished_signal.emit(ok, "" if ok else "失能失败")
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


class ColumnHomingThread(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, column: Column, action: str = "set_zero"):
        super().__init__()
        self.column = column
        self.action = action

    def run(self):
        try:
            if self.action == "return_home":
                if self.column.get_control_mode() != CONTROL_MODE_POSITION:
                    if not self.column.switch_to_position_mode():
                        self.finished_signal.emit(
                            False, t("log_column_mode_position_failed")
                        )
                        return
                ok = self.column.return_home()
                msg = "" if ok else (self.column.homing_detail or "回零失败")
            else:
                if self.column.get_control_mode() != CONTROL_MODE_VELOCITY:
                    if not self.column.switch_to_velocity_mode():
                        self.finished_signal.emit(
                            False, t("log_column_mode_velocity_failed")
                        )
                        return
                ok = self.column.start_homing()
                msg = "" if ok else (self.column.homing_detail or "设置零点失败")
            self.finished_signal.emit(ok, msg)
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


class ColumnStatusThread(QThread):
    finished_signal = Signal(object)

    def __init__(self, column: Column):
        super().__init__()
        self.column = column

    def run(self):
        try:
            self.column.refresh_status()
            self.finished_signal.emit(self.column.get_status())
        except Exception as exc:
            self.finished_signal.emit({"error": str(exc)})


class ColumnController:
    """升降台 UI 控制器。"""

    def __init__(self, main_controller):
        self.main = main_controller
        self.window = main_controller.window
        self.settings = main_controller.settings
        self.log = main_controller.log
        self.column: Optional[Column] = None

        self._connected = False
        self._position_move_active = False
        self._jog_active = False
        self._jog_velocity_mps = 0.0
        self._jog_logged = False
        self._status_thread: Optional[ColumnStatusThread] = None
        self._homing_thread: Optional[ColumnHomingThread] = None
        self._homing_active = False
        self._control_mode = CONTROL_MODE_VELOCITY

        self._monitor_timer = QTimer()
        self._monitor_timer.timeout.connect(self._on_monitor_tick)
        self._jog_timer = QTimer()
        self._jog_timer.timeout.connect(self._on_jog_tick)
        self.is_monitoring = False

        self._init_column()
        self._wire_signals()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _init_column(self):
        if not self.settings.get("column_enabled", True):
            self.column = None
            return

        self.column = Column(
            can_interface=self.settings.get("column_can", "can3"),
            node_id=int(self.settings.get("column_node_id", 16)),
            counts_per_meter=float(self.settings.get("column_counts_per_meter", 2_000_000.0)),
            max_velocity_mps=float(self.settings.get("column_max_velocity_mps", 0.10)),
            homing_speed_mps=float(self.settings.get("column_homing_speed_mps", 0.010)),
            homing_timeout_sec=float(self.settings.get("column_homing_timeout_sec", 60.0)),
            profile_acceleration=int(self.settings.get("column_profile_acceleration", 50_000)),
            profile_deceleration=int(self.settings.get("column_profile_deceleration", 50_000)),
            invert_command=bool(self.settings.get("column_invert_command", True)),
            invert_feedback=bool(self.settings.get("column_invert_feedback", True)),
            di_active_low=bool(self.settings.get("column_di_active_low", True)),
            homing_configure_di=bool(self.settings.get("column_homing_configure_di", True)),
            home_di_channel=int(self.settings.get("column_home_di_channel", 4)),
            pot_di_channel=int(self.settings.get("column_pot_di_channel", 5)),
            not_di_channel=int(self.settings.get("column_not_di_channel", 6)),
            di4_homing_func=int(self.settings.get("column_di4_homing_func", 0x16)),
            di5_pot_func=int(self.settings.get("column_di5_pot_func", 0x01)),
            di6_not_func=int(self.settings.get("column_di6_not_func", 0x02)),
            lower_switch_position_m=float(
                self.settings.get("column_lower_switch_position_m", 0.0)
            ),
            home_switch_position_m=float(
                self.settings.get("column_home_switch_position_m", 0.640)
            ),
            upper_switch_position_m=float(
                self.settings.get("column_upper_switch_position_m", 0.940)
            ),
            switch_position_tolerance_m=float(
                self.settings.get("column_switch_position_tolerance_m", 0.008)
            ),
            min_position_m=float(self.settings.get("column_min_position_m", -0.650)),
            max_position_m=float(self.settings.get("column_max_position_m", 0.300)),
            log=self.log,
        )

        max_vel = self.column.max_velocity_mps
        max_pos = self.column.max_position_m
        min_pos = self.column.min_position_m
        if hasattr(self.window, "apply_column_position_limits"):
            self.window.apply_column_position_limits(min_pos, max_pos, max_vel)
        default_speed = float(self.settings.get("column_default_speed_mps", 0.05))
        if hasattr(self.window, "spin_column_move_speed"):
            spin = self.window.spin_column_move_speed
            spin.setValue(min(default_speed, spin.maximum()))
        if hasattr(self.window, "spin_column_jog_speed"):
            jog = self.window.spin_column_jog_speed
            jog.setValue(min(default_speed, jog.maximum()))

    def _wire_signals(self):
        w = self.window
        mapping = [
            ("btn_column_connect", self.connect_column),
            ("btn_column_disconnect", self.disconnect_column),
            ("btn_column_enable", self.enable_drive),
            ("btn_column_disable", self.disable_drive),
            ("btn_column_estop", self.quick_stop),
            ("btn_column_move_to", self.move_to_target),
            ("btn_column_stop", self.stop_motion),
            ("btn_column_set_zero", self.request_set_zero),
            ("btn_column_return_home", self.request_return_home),
            ("btn_column_stop_homing", self.abort_homing),
            ("btn_column_check", self.check_motors),
            ("btn_column_toggle_monitor", self.toggle_monitoring),
            ("btn_column_mode_velocity", self._select_velocity_mode),
            ("btn_column_mode_position", self._select_position_mode),
        ]
        for attr, handler in mapping:
            btn = getattr(w, attr, None)
            if btn is not None:
                btn.clicked.connect(handler)

        for attr, start_handler, stop_handler in (
            ("btn_column_jog_up", self._jog_up_pressed, self._jog_released),
            ("btn_column_jog_down", self._jog_down_pressed, self._jog_released),
        ):
            btn = getattr(w, attr, None)
            if btn is not None:
                btn.pressed.connect(start_handler)
                btn.released.connect(stop_handler)

    def _position_or_homing_busy(self) -> bool:
        """位置/设零占用中（不含点动本身）。"""
        if self._homing_active:
            return True
        if self._position_move_active:
            return True
        if self.column and (
            self.column.homing_in_progress or self.column.position_move_in_progress
        ):
            return True
        return False

    def _motion_busy(self) -> bool:
        if self._jog_active:
            return True
        return self._position_or_homing_busy()

    def _ensure_column(self) -> bool:
        if not self.column:
            self.log(t("log_column_disabled"), "WARNING")
            return False
        return True

    def _ensure_connected(self) -> bool:
        if not self._ensure_column():
            return False
        if not self._connected:
            self.log(t("log_column_not_connected"), "WARNING")
            return False
        return True

    def _ensure_enabled(self) -> bool:
        if not self._ensure_connected():
            return False
        if self.column and not self.column.is_enabled:
            self.log(t("log_column_not_enabled"), "WARNING")
            return False
        return True

    def _refresh_tool_buttons(self):
        if hasattr(self.window, "_update_column_tool_buttons"):
            self.window._update_column_tool_buttons()

    def connect_column(self):
        """连接升降台 CAN（主线程同步，避免 QThread 生命周期与跨线程问题）。"""
        if self._connected:
            self.log(t("log_column_already_connected"), "WARNING")
            return
        self._ensure_column_connected()

    def _ensure_column_connected(self) -> bool:
        """确保升降台已连接；只建立 CAN 连接，不使能驱动。"""
        if not self._ensure_column():
            return False
        if self._connected:
            return True
        self.log(t("log_column_connecting"), "INFO")
        try:
            if not verify_can_interface(self.column.can_interface):
                self._on_connect_finished(
                    False,
                    f"CAN 接口 {self.column.can_interface} 未启动",
                )
                return False
            self.column.connect()
            self._on_connect_finished(True, "")
        except Exception as exc:
            self._on_connect_finished(False, str(exc))
            return False
        return self._connected

    def _connect_column_for_enable(self) -> bool:
        """兼容旧调用：使能前先确保连接。"""
        return self._ensure_column_connected()

    def disconnect_column(self):
        """断开升降台 CAN 连接。"""
        if not self._ensure_column():
            return
        if not self._connected:
            self.log(t("log_column_not_connected"), "WARNING")
            return
        self.is_monitoring = False
        self._monitor_timer.stop()
        if hasattr(self.window, "btn_column_toggle_monitor"):
            self.window.btn_column_toggle_monitor.setText(t("btn_start_monitor"))
        try:
            self.column.close()
        except Exception as exc:
            self.log(t("log_column_disconnect_failed", error=str(exc)), "ERROR")
            return
        self._connected = False
        self._homing_active = False
        self._position_move_active = False
        self._stop_jog()
        self.log(t("log_column_disconnected"), "INFO")
        self._refresh_tool_buttons()
        self._refresh_ui_state()

    def _on_connect_finished(self, ok: bool, message: str):
        if ok:
            self._connected = True
            self.log(t("log_column_connected"), "SUCCESS")
        else:
            self.log(t("log_column_connect_failed", error=message), "ERROR")
        self._refresh_tool_buttons()
        self._refresh_ui_state()

    def enable_drive(self):
        """使能升降台驱动（主线程同步，避免 QThread 生命周期与跨线程 CAN 问题）。"""
        if not self._ensure_column_connected():
            return
        if self._homing_active:
            self.log(t("log_column_homing_busy"), "WARNING")
            return
        self.log(t("log_column_enabling"), "INFO")
        try:
            ok = self.column.enable()
            self._on_enable_finished(ok, "" if ok else "使能失败")
        except Exception as exc:
            self._on_enable_finished(False, str(exc))

    def _on_enable_finished(self, ok: bool, message: str):
        if ok:
            self.log(t("log_column_enabled"), "SUCCESS")
            if self.column:
                if self.column.switch_to_velocity_mode():
                    self._control_mode = CONTROL_MODE_VELOCITY
                else:
                    self.log(t("log_column_mode_velocity_failed"), "WARNING")
        else:
            self.log(t("log_column_enable_failed", error=message), "ERROR")
        self._refresh_ui_state()

    def disable_drive(self):
        """失能升降台驱动（主线程同步）。"""
        if not self._ensure_connected():
            return
        self.log(t("log_column_disabling"), "INFO")
        try:
            ok = self.column.disable()
            self._on_disable_finished(ok, "" if ok else "失能失败")
            if ok:
                self.disconnect_column()
        except Exception as exc:
            self._on_disable_finished(False, str(exc))

    def _on_disable_finished(self, ok: bool, message: str):
        if ok:
            self.log(t("log_column_disabled_ok"), "SUCCESS")
        else:
            self.log(t("log_column_disable_failed", error=message), "ERROR")
        self._refresh_ui_state()

    def _select_velocity_mode(self):
        if not self._ensure_enabled():
            return
        if self._motion_busy():
            self.log(t("log_column_homing_busy"), "WARNING")
            return
        self._stop_jog()
        if not self.column.switch_to_velocity_mode():
            self.log(t("log_column_mode_velocity_failed"), "ERROR")
        else:
            self._control_mode = CONTROL_MODE_VELOCITY
            self.log(t("log_column_mode_velocity_active"), "INFO")
        self._refresh_ui_state()

    def _select_position_mode(self):
        if not self._ensure_enabled():
            return
        if self._motion_busy():
            self.log(t("log_column_homing_busy"), "WARNING")
            return
        self._stop_jog()
        if not self.column.switch_to_position_mode():
            self.log(t("log_column_mode_position_failed"), "ERROR")
        else:
            self._control_mode = CONTROL_MODE_POSITION
            self.log(t("log_column_mode_position_active"), "INFO")
        self._refresh_ui_state()

    def stop_motion(self):
        if not self._ensure_connected():
            return
        if self._homing_active:
            self.column.abort_homing()
            self.column.stop_motion()
            self.log(t("log_column_homing_abort"), "WARNING")
            return
        self._stop_jog()
        if self.column:
            self.column.stop_motion()
        self._position_move_active = False
        self.log(t("log_column_motion_stopped"), "INFO")
        self._refresh_ui_state()

    def _stop_jog(self) -> None:
        self._jog_timer.stop()
        self._jog_velocity_mps = 0.0
        if self._jog_active and self.column:
            self.column.jog_velocity(0.0)
        self._jog_active = False
        self._jog_logged = False

    def _apply_jog_velocity(self) -> None:
        if not self.column or not self._jog_active:
            return
        if not self.column.jog_velocity(self._jog_velocity_mps):
            self._stop_jog()
            self.log(t("log_column_jog_failed"), "WARNING")
            self._refresh_ui_state()

    def _on_jog_tick(self) -> None:
        self._apply_jog_velocity()

    def _start_jog(self, direction: int) -> None:
        if not self._ensure_enabled():
            return
        if self._control_mode != CONTROL_MODE_VELOCITY:
            self.log(t("log_column_mode_velocity_required"), "WARNING")
            return
        if self._position_or_homing_busy():
            self.log(t("log_column_homing_busy"), "WARNING")
            return
        speed = float(self.window.get_column_jog_speed_mps())
        self._jog_velocity_mps = speed if direction > 0 else -speed
        self._jog_active = True
        self._apply_jog_velocity()
        if not self._jog_active:
            return
        self._jog_timer.start(100)
        if not self._jog_logged:
            self.log(
                t("log_column_jog_start", speed=self._jog_velocity_mps),
                "INFO",
            )
            self._jog_logged = True

    def _jog_up_pressed(self):
        self._start_jog(1)

    def _jog_down_pressed(self):
        self._start_jog(-1)

    def _jog_released(self):
        w = self.window
        up = getattr(w, "btn_column_jog_up", None)
        down = getattr(w, "btn_column_jog_down", None)
        if (up is not None and up.isDown()) or (down is not None and down.isDown()):
            return
        if self._jog_active and self._jog_logged:
            self.log(t("log_column_jog_stop"), "INFO")
        self._stop_jog()
        self._refresh_ui_state()
        if self.is_monitoring:
            self._poll_status_once()

    def quick_stop(self):
        if not self._ensure_column():
            return
        self._stop_jog()
        if self.column and self._connected:
            self.column.quick_stop()
        self._position_move_active = False
        self.log(t("log_column_estop"), "WARNING")
        self._refresh_ui_state()

    def move_to_target(self):
        """移动到目标位置（主线程同步，避免 socketcan 跨线程崩溃）。"""
        if not self._ensure_enabled():
            return
        if self._control_mode != CONTROL_MODE_POSITION:
            self.log(t("log_column_mode_position_required"), "WARNING")
            return
        if self._motion_busy():
            self.log(t("log_column_homing_busy"), "WARNING")
            return

        self._stop_jog()
        target = float(self.window.get_column_target_position_m())
        speed = float(self.window.get_column_move_speed_mps())
        self._position_move_active = True
        self.log(t("log_column_move_to_start", target=target, speed=speed), "INFO")
        try:
            ok = self.column.move_to_user_position(target, speed_mps=speed)
            self._on_position_move_finished(ok, "" if ok else "位置运动失败", target)
        except Exception as exc:
            self._on_position_move_finished(False, str(exc), target)

    def _on_position_move_finished(self, ok: bool, message: str, target_m: float):
        self._position_move_active = False
        if ok:
            self.log(t("log_column_move_to_success", target=target_m), "SUCCESS")
        else:
            self.log(t("log_column_move_to_failed", error=message), "ERROR")
        self._refresh_ui_state()
        if self.is_monitoring:
            self._poll_status_once()

    def _start_homing_action(self, action: str) -> None:
        """在专用线程中执行设零/回零，保持停止和急停按钮可用。"""
        if not self.column:
            self._on_homing_finished(False, t("log_column_disabled"))
            return
        if self._homing_thread and self._homing_thread.isRunning():
            self.log(t("log_column_homing_busy"), "WARNING")
            return

        thread = ColumnHomingThread(self.column, action)
        thread.finished_signal.connect(self._on_homing_finished)
        thread.finished.connect(self._on_homing_thread_stopped)
        self._homing_thread = thread
        thread.start()
        self._refresh_ui_state()

    def _on_homing_thread_stopped(self):
        thread = self._homing_thread
        if thread is not None and not thread.isRunning():
            thread.deleteLater()
            self._homing_thread = None

    def request_set_zero(self):
        if not self._ensure_column_connected():
            return
        if self._homing_active:
            self.log(t("log_column_homing_busy"), "WARNING")
            return

        confirm = QMessageBox.question(
            self.window,
            t("dialog_set_zero_title"),
            t("dialog_column_set_zero_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._stop_jog()
        if self.column and self.column.is_enabled:
            self.column.stop_motion()
        self._homing_active = True
        self.log(t("log_column_set_zero_start"), "INFO")
        self._start_homing_action("set_zero")

    def request_return_home(self):
        if not self._ensure_enabled():
            return
        if not self.column.homing_complete:
            self.log(t("log_column_need_set_zero_first"), "WARNING")
            return
        if self._homing_active:
            self.log(t("log_column_homing_busy"), "WARNING")
            return

        confirm = QMessageBox.question(
            self.window,
            t("dialog_column_return_home_title"),
            t("dialog_column_return_home_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.stop_motion()
        self._homing_active = True
        self.log(t("log_column_return_home_start"), "INFO")
        self._start_homing_action("return_home")

    def abort_homing(self):
        if self.column and self._homing_active:
            self.column.abort_homing()
            self.log(t("log_column_homing_abort"), "WARNING")

    def _on_homing_finished(self, ok: bool, message: str):
        self._homing_active = False
        if ok:
            self.log(t("log_column_homing_success"), "SUCCESS")
        else:
            if message == "home_not_found_stopped_at_midpoint":
                message = t("log_column_home_not_found_midpoint")
            self.log(t("log_column_homing_failed", error=message), "ERROR")
        self._refresh_ui_state()
        if self.is_monitoring:
            self._poll_status_once()

    def toggle_monitoring(self):
        if not self._ensure_connected():
            return
        if self.is_monitoring:
            self.is_monitoring = False
            self._monitor_timer.stop()
            self.window.btn_column_toggle_monitor.setText(t("btn_start_monitor"))
            self.log(t("log_monitor_stopped"), "INFO")
        else:
            self.is_monitoring = True
            self._monitor_timer.start(500)
            self.window.btn_column_toggle_monitor.setText(t("btn_stop_monitor"))
            self.log(t("log_monitor_started"), "INFO")
            self._poll_status_once()

    def check_motors(self):
        if not self._ensure_connected():
            return
        self._poll_status_once()

    def _on_monitor_tick(self):
        if not self.is_monitoring:
            return
        if self._homing_active:
            self._refresh_ui_state()
            return
        self._poll_status_once()

    def _poll_status_once(self):
        if not self.column or not self._connected or self._homing_active:
            return
        try:
            self.column.refresh_status()
            self._on_status_received(self.column.get_status())
        except Exception as exc:
            self._on_status_received({"error": str(exc)})

    def _on_status_received(self, status: dict):
        if "error" in status:
            return
        self._update_status_table(status)
        self._refresh_ui_state(status)

    def _update_status_table(self, status: dict):
        table = getattr(self.window, "column_table", None)
        if table is None:
            return
        table.setRowCount(1)
        cells = [
            status.get("can_interface", ""),
            str(status.get("node_id", "")),
            f"{status.get('position_m', 0.0):.4f}",
            f"{status.get('velocity_mps', 0.0):.4f}",
            status.get("cia402_state", ""),
            t("table_status_online") if not status.get("fault") else t("column_status_fault"),
            t("column_switch_on") if status.get("home_switch") else t("column_switch_off"),
            t("column_switch_on") if status.get("upper_switch") else t("column_switch_off"),
            t("column_switch_on") if status.get("lower_switch") else t("column_switch_off"),
        ]
        from PySide6.QtWidgets import QTableWidgetItem
        for col, text in enumerate(cells):
            table.setItem(0, col, QTableWidgetItem(str(text)))

    def _refresh_ui_state(self, status: Optional[dict] = None):
        w = self.window
        comm_ok = self._connected and status is not None and "error" not in (status or {})
        enabled = bool(self.column and self.column.is_enabled)
        homing = self._motion_busy()
        drive_busy = self._position_or_homing_busy()
        homed = bool(self.column and self.column.homing_complete)
        if self.column:
            self._control_mode = self.column.get_control_mode()
        in_velocity = self._control_mode == CONTROL_MODE_VELOCITY
        in_position = self._control_mode == CONTROL_MODE_POSITION
        mode_switch_ok = self._connected and enabled and not homing and not drive_busy

        velocity_panel = getattr(w, "column_velocity_panel", None)
        if velocity_panel is not None:
            velocity_panel.setVisible(in_velocity)
        position_panel = getattr(w, "column_position_panel", None)
        if position_panel is not None:
            position_panel.setVisible(in_position)
        mode_divider = getattr(w, "column_mode_divider", None)
        if mode_divider is not None:
            mode_divider.setVisible(in_velocity and in_position)

        detail = getattr(w, "label_column_detail", None)
        if detail is not None:
            if homing:
                homing_detail = self.column.homing_detail if self.column else ""
                detail_key = {
                    "configuring": "column_homing_configuring",
                    "moving_up_to_home": "column_homing_moving_up",
                    "moving_down_to_home": "column_homing_moving_down",
                    "moving_to_midpoint_no_home": "column_homing_moving_midpoint",
                }.get(homing_detail)
                detail.setText(
                    t(
                        "column_detail_homing",
                        detail=t(detail_key) if detail_key else homing_detail,
                    )
                )
            elif comm_ok and status:
                mode_label = (
                    t("column_mode_velocity_short")
                    if in_velocity
                    else t("column_mode_position_short")
                )
                detail.setText(
                    t(
                        "column_detail_status",
                        pos=status.get("position_m", 0.0),
                        vel=status.get("velocity_mps", 0.0),
                        homed=t("column_homed_yes") if homed else t("column_homed_no"),
                    )
                    + " | "
                    + t("column_detail_mode", mode=mode_label)
                )
            elif self._connected:
                detail.setText(t("column_detail_waiting"))
            else:
                detail.setText(t("column_detail_disconnected"))

        enable_btn = getattr(w, "btn_column_enable", None)
        if enable_btn is not None:
            enable_btn.setEnabled(not enabled and not homing)

        move_btn = getattr(w, "btn_column_move_to", None)
        if move_btn is not None:
            move_btn.setEnabled(self._connected and enabled and in_position and not homing)

        for name in ("btn_column_jog_up", "btn_column_jog_down"):
            btn = getattr(w, name, None)
            if btn is not None:
                jog_ok = self._connected and enabled and in_velocity and not drive_busy
                if self._jog_active and btn.isDown():
                    jog_ok = True
                btn.setEnabled(jog_ok)

        for name in ("spin_column_target", "spin_column_move_speed"):
            spin = getattr(w, name, None)
            if spin is not None:
                spin.setEnabled(self._connected and enabled and in_position and not homing)

        for name in ("spin_column_jog_speed",):
            spin = getattr(w, name, None)
            if spin is not None:
                spin.setEnabled(
                    self._connected and enabled and in_velocity and not drive_busy
                )

        vel_mode_btn = getattr(w, "btn_column_mode_velocity", None)
        if vel_mode_btn is not None:
            vel_mode_btn.setChecked(in_velocity)
            vel_mode_btn.setEnabled(mode_switch_ok and not in_velocity)

        pos_mode_btn = getattr(w, "btn_column_mode_position", None)
        if pos_mode_btn is not None:
            pos_mode_btn.setChecked(in_position)
            pos_mode_btn.setEnabled(mode_switch_ok and not in_position)

        set_zero_btn = getattr(w, "btn_column_set_zero", None)
        if set_zero_btn is not None:
            set_zero_btn.setEnabled(self._connected and not homing)

        for name in ("btn_column_disable",):
            btn = getattr(w, name, None)
            if btn is not None:
                btn.setEnabled(self._connected and enabled and not homing)

        for name in ("btn_column_estop", "btn_column_stop"):
            btn = getattr(w, name, None)
            if btn is not None:
                btn.setEnabled(self._connected)

        self._refresh_tool_buttons()

        stop_homing = getattr(w, "btn_column_stop_homing", None)
        if stop_homing is not None:
            stop_homing.setEnabled(self._connected and homing)

        return_home = getattr(w, "btn_column_return_home", None)
        if return_home is not None:
            return_home.setEnabled(self._connected and enabled and homed and not homing)

    def shutdown(self):
        self._monitor_timer.stop()
        self._stop_jog()
        if self.column and self._homing_thread and self._homing_thread.isRunning():
            self.column.abort_homing()
            self._homing_thread.wait(3000)
        if self.column:
            try:
                self.column.close()
            except Exception:
                pass
