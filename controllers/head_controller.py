#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""头部控制器 — 2×RS00 yaw/pitch，对齐 HeadJointSliderPanel。"""

from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidgetItem

from controllers.arm_controller import translate_motor_status

from openflex_driver.head import Head, JOINT_PITCH, JOINT_YAW, DEFAULT_MOTOR_IDS
from openflex_driver._lib.can_utils import verify_can_interface
from utils.i18n import t
from utils.input_limits import (
    HEAD_JOINT_LIMIT_DEG,
    HEAD_STEP_MAX_DEG,
    HEAD_STEP_MIN_DEG,
)

HEAD_MOTOR_IDS = [JOINT_YAW, JOINT_PITCH]
HEAD_JOINT_LABEL_KEYS = {
    JOINT_YAW: "head_joint_yaw",
    JOINT_PITCH: "head_joint_pitch",
}
HEAD_ENABLED_MODE_MARKERS = ("motor mode", "mit")


class HeadController:
    """头部 UI 控制器。"""

    def __init__(self, main_controller):
        self.main = main_controller
        self.window = main_controller.window
        self.settings = main_controller.settings
        self.log = main_controller.log
        self.head: Optional[Head] = None
        self._connected = False
        self._enable_last_status: dict = {}
        self._head_motor_ids = list(HEAD_MOTOR_IDS)
        self._joint_positions = {mid: 0.0 for mid in self._head_motor_ids}
        self._joints_need_reenable = set()

        self._monitor_timer = QTimer()
        self._monitor_timer.timeout.connect(self._on_monitor_tick)
        self.is_monitoring = False

        self._joint_repeat_timer = QTimer()
        self._joint_repeat_timer.timeout.connect(self._on_joint_repeat)
        self._active_joint: Optional[int] = None
        self._active_direction: Optional[int] = None

        self._label_refresh_timer = QTimer()
        self._label_refresh_timer.timeout.connect(self._refresh_joint_labels)

        self._init_head()
        self._wire_signals()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _init_head(self):
        if not self.settings.get("head_enabled", True):
            self.head = None
            return
        motor_ids = self.settings.get("head_motor_ids", DEFAULT_MOTOR_IDS)
        if isinstance(motor_ids, list):
            motor_ids = [int(x) for x in motor_ids]
        else:
            motor_ids = DEFAULT_MOTOR_IDS
        self._set_head_motor_ids(motor_ids)
        try:
            joint_limit_deg = float(
                self.settings.get("head_joint_limit_deg", HEAD_JOINT_LIMIT_DEG)
            )
            self.head = Head(
                can_channel=self.settings.get("head_can", "can2"),
                motor_ids=motor_ids,
                auto_enable_can=False,
                log=self.log,
                joint_limit_rad=math.radians(joint_limit_deg),
                active_zero_torque=float(
                    self.settings.get(
                        "head_active_zero_torque",
                        self.settings.get("chassis_active_zero_torque", 1.5),
                    )
                ),
                active_zero_velocity=float(
                    self.settings.get(
                        "head_active_zero_velocity",
                        self.settings.get("chassis_active_zero_velocity", 0.3),
                    )
                ),
                active_zero_pos_per_yaw=float(
                    self.settings.get("head_yaw_active_zero_pos_per", 0.5)
                ),
                active_zero_pos_per_pitch=float(
                    self.settings.get(
                        "head_pitch_active_zero_pos_per",
                        self.settings.get("head_active_zero_pos_per", 0.75),
                    )
                ),
                active_zero_max_duration=float(
                    self.settings.get(
                        "head_active_zero_max_duration",
                        self.settings.get("chassis_active_zero_max_duration", 20.0),
                    )
                ),
            )
            kp = float(self.settings.get("head_kp_percent", 20.0))
            kd = float(self.settings.get("head_kd_percent", 100.0))
            self.head.set_kp_kd_percent(kp, kd)
            step = float(self.settings.get("head_default_step_deg", 5.0))
            min_step = float(self.settings.get("head_step_min_deg", HEAD_STEP_MIN_DEG))
            max_step = float(self.settings.get("head_step_max_deg", HEAD_STEP_MAX_DEG))
            max_step = min(max_step, joint_limit_deg)
            if hasattr(self.window, "apply_head_step_limits"):
                self.window.apply_head_step_limits(min_step, max_step, step)
            elif hasattr(self.window, "spin_head_step"):
                self.window.spin_head_step.setValue(step)
        except Exception as exc:
            self.head = None
            self.log(t("log_head_init_failed", error=str(exc)), "WARNING")

    def _set_head_motor_ids(self, motor_ids: list[int]) -> None:
        self._head_motor_ids = [int(mid) for mid in motor_ids]
        for mid in self._head_motor_ids:
            self._joint_positions.setdefault(mid, 0.0)

    def _current_head_motor_ids(self) -> list[int]:
        if self.head and getattr(self.head, "motor_ids", None):
            return [int(mid) for mid in self.head.motor_ids]
        return list(self._head_motor_ids)

    def _joint_label(self, motor_id: int) -> str:
        if motor_id == JOINT_YAW:
            return t("head_joint_yaw")
        if motor_id == JOINT_PITCH:
            return t("head_joint_pitch")
        return str(motor_id)

    def _wire_signals(self):
        w = self.window
        for attr, handler in (
            ("btn_head_connect", self.connect_head),
            ("btn_head_disconnect", self.disconnect_head),
            ("btn_head_enable", self.enable_motors),
            ("btn_head_disable", self.disable_motors),
            ("btn_head_sync", self.check_can_status),
            ("btn_head_check", self.check_motors),
            ("btn_head_toggle_monitor", self.toggle_monitoring),
        ):
            btn = getattr(w, attr, None)
            if btn is not None:
                btn.clicked.connect(handler)

        for ctrl in getattr(w, "head_joint_controls", []):
            motor_id = ctrl["motor_id"]
            ctrl["btn_zero_passive"].clicked.connect(
                lambda _=False, m=motor_id: self.set_zero_passive(m)
            )
            ctrl["btn_zero_active"].clicked.connect(
                lambda _=False, m=motor_id: self.set_zero_active(m)
            )
            ctrl["btn_go_zero"].clicked.connect(
                lambda _=False, m=motor_id: self.go_home(m)
            )

        for idx, motor_id in enumerate(self._current_head_motor_ids()):
            minus = getattr(w, f"btn_head_j{idx}_minus", None)
            plus = getattr(w, f"btn_head_j{idx}_plus", None)
            if minus is not None:
                minus.pressed.connect(lambda _=False, m=motor_id: self._on_joint_pressed(m, -1))
                minus.released.connect(self._on_joint_released)
            if plus is not None:
                plus.pressed.connect(lambda _=False, m=motor_id: self._on_joint_pressed(m, 1))
                plus.released.connect(self._on_joint_released)

    def _ensure_head(self) -> bool:
        if not self.head:
            self.log(t("log_head_disabled"), "WARNING")
            return False
        return True

    def _ensure_connected(self) -> bool:
        if not self._ensure_head():
            return False
        if not self._connected:
            self.log(t("log_head_not_connected"), "WARNING")
            return False
        return True

    def _refresh_joint_labels(self, motor_ids: Optional[list] = None) -> None:
        """刷新关节标签，显示已跟踪的逻辑角度（不依赖滞后反馈）。"""
        for mid in motor_ids or self._current_head_motor_ids():
            logical = self._joint_positions.get(mid, 0.0)
            self._update_joint_value_label(mid, logical)

    def _start_label_refresh(self) -> None:
        interval = int(self.settings.get("head_monitor_interval_ms", 50))
        self._label_refresh_timer.start(max(30, interval))

    def _stop_label_refresh(self) -> None:
        self._label_refresh_timer.stop()

    def _set_joint_logical_angle(self, motor_id: int, logical: float) -> None:
        self._joint_positions[motor_id] = float(logical)
        self._update_joint_value_label(motor_id, logical)

    def _read_logical_angle(self, motor_id: int) -> Optional[float]:
        try:
            status = self.head.get_motor_status(motor_id, timeout=0.15)
            if status and status.get("angle") is not None:
                return self.head.to_logical_angle(motor_id, float(status["angle"]))
        except Exception:
            pass
        return None

    def _sync_joint_position_from_motor(self, motor_id: int) -> None:
        """仅在使能/检查等场景下，用反馈初始化跟踪角度。"""
        logical = self._read_logical_angle(motor_id)
        if logical is not None:
            self._set_joint_logical_angle(motor_id, logical)

    def _hold_joint_at_logical(self, motor_id: int, logical: float) -> None:
        try:
            self.head.move_to_mit(
                motor_id=motor_id,
                position=logical,
                wait_response=False,
                timeout=0.05,
            )
        except Exception:
            return
        self._set_joint_logical_angle(motor_id, logical)

    def _hold_joint_position(self, motor_id: int) -> None:
        """使能后保持当前反馈位置，避免默认回到机械零位。"""
        logical = self._joint_positions.get(motor_id, 0.0)
        feedback = self._read_logical_angle(motor_id)
        if feedback is not None:
            logical = feedback
        try:
            self.head.move_to_mit(
                motor_id=motor_id,
                position=logical,
                wait_response=False,
                timeout=0.05,
            )
        except Exception:
            return
        self._set_joint_logical_angle(motor_id, logical)

    def _ensure_joint_enabled(self, motor_id: int) -> bool:
        if not self._ensure_connected():
            return False
        if motor_id in self._joints_need_reenable:
            try:
                state = self.head.enable_motor_by_id(motor_id, verbose=False)
            except Exception as exc:
                self.log(f"ID={motor_id} 设零/回零后重新使能失败: {exc}", "ERROR")
                return False
            if state != 0:
                self.log(f"ID={motor_id} 设零/回零后重新使能失败, state={state}", "ERROR")
                return False
            self._joints_need_reenable.discard(motor_id)
            self.head.is_enabled = True
            self._hold_joint_position(motor_id)
            self._start_label_refresh()
            self.log(f"ID={motor_id} 设零/回零后已重新使能", "SUCCESS")
        if not self.head.is_enabled:
            self.log(t("log_head_not_enabled"), "WARNING")
            return False
        return True

    def _apply_immediate_zero_display(self, motor_id: int) -> None:
        """手动设零时立即将当前姿态显示为逻辑零位。"""
        try:
            status = self.head.get_motor_status(motor_id, timeout=0.15)
            if status and status.get("angle") is not None:
                raw = float(status["angle"])
                self.head.set_zero_offset(motor_id, raw)
                self._set_joint_logical_angle(motor_id, 0.0)
        except Exception:
            pass

    def _ensure_enabled(self) -> bool:
        if not self._ensure_connected():
            return False
        if not self.head.is_enabled:
            self.log(t("log_head_not_enabled"), "WARNING")
            return False
        return True

    def _refresh_tool_buttons(self):
        if hasattr(self.window, "_update_head_tool_buttons"):
            self.window._update_head_tool_buttons()

    def _is_enabled_status(self, info: Optional[dict]) -> bool:
        if not info:
            return False
        mode_status = str(info.get("mode_status", "")).lower()
        return any(marker in mode_status for marker in HEAD_ENABLED_MODE_MARKERS)

    def _read_head_motor_status(self, motor_id: int, timeout: float = 0.2) -> Optional[dict]:
        with self.head._can_lock:
            return self.head.get_motor_status(motor_id, timeout=timeout)

    def _enable_motors_sync(self) -> tuple[dict, list]:
        self._enable_last_status = {}
        try:
            results = self.head.enable(verbose=False)
            failed = self._failed_enable_results(results)
            if failed:
                results = self._retry_failed_enable(results)
                failed = self._failed_enable_results(results)
            if failed:
                results = self._verify_enabled_results(results)
                failed = self._failed_enable_results(results)
            return results, failed
        except Exception as exc:
            results = self._verify_enabled_results({})
            failed = self._failed_enable_results(results)
            if results and not failed:
                return results, []
            return results, [{
                "arm": t("tab_head"),
                "can_channel": self.head.can_channel,
                "motor_id": -1,
                "error": str(exc),
            }]

    def _retry_failed_enable(self, results: dict) -> dict:
        retried = dict(results)
        for mid, state in list(results.items()):
            if state == 0:
                continue
            time.sleep(0.12)
            try:
                retried[mid] = self.head.enable_motor_by_id(mid, verbose=False)
            except Exception as exc:
                errors = getattr(self.head, "_last_enable_errors", {})
                errors[mid] = str(exc)
                self.head._last_enable_errors = errors
                retried[mid] = 1
        return retried

    def _verify_enabled_results(self, results: dict) -> dict:
        verified = {mid: results.get(mid, 1) for mid in self.head.motor_ids}
        for mid in self.head.motor_ids:
            try:
                info = self._read_head_motor_status(mid, timeout=0.2)
            except Exception:
                info = None
            self._enable_last_status[mid] = info
            if self._is_enabled_status(info):
                verified[mid] = 0
        return verified

    def _failed_enable_results(self, results: dict) -> list:
        failed = []
        for mid, state in results.items():
            if state != 0:
                failed.append({
                    "arm": t("tab_head"),
                    "can_channel": self.head.can_channel,
                    "motor_id": mid,
                    "error": t("motor_enable_failed"),
                    "status": self._enable_last_status.get(mid),
                })
        return failed

    def connect_head(self):
        """连接头部 CAN（主线程同步，避免 socketcan 跨线程崩溃）。"""
        if self._connected:
            self.log(t("log_head_already_connected"), "WARNING")
            return
        self._ensure_head_connected()

    def _ensure_head_connected(self) -> bool:
        """确保头部已连接；只建立 CAN 连接，不使能电机。"""
        if not self.settings.get("head_enabled", True):
            self.log(t("log_head_disabled"), "WARNING")
            return False
        if self.head is None:
            self._init_head()
        if not self._ensure_head():
            return False
        if self._connected:
            return True
        self.log(t("log_head_connecting"), "INFO")
        try:
            if not verify_can_interface(self.head.can_channel):
                self._on_connect_finished(
                    False, f"CAN {self.head.can_channel} 未启动"
                )
                return False
            self.head.connect()
            self._on_connect_finished(True, "")
        except Exception as exc:
            self._on_connect_finished(False, str(exc))
            return False
        return self._connected

    def _connect_head_for_enable(self) -> bool:
        """兼容旧调用：使能前先确保连接。"""
        return self._ensure_head_connected()

    def disconnect_head(self):
        """断开头部 CAN 连接。"""
        if not self._ensure_head():
            return
        if not self._connected:
            self.log(t("log_head_not_connected"), "WARNING")
            return
        self.is_monitoring = False
        self._monitor_timer.stop()
        self._joint_repeat_timer.stop()
        self._stop_label_refresh()
        if hasattr(self.window, "btn_head_toggle_monitor"):
            self.window.btn_head_toggle_monitor.setText(t("btn_start_monitor"))
        try:
            self.head.disconnect()
        except Exception as exc:
            self.log(t("log_head_disconnect_failed", error=str(exc)), "ERROR")
            return
        self._connected = False
        self.log(t("log_head_disconnected"), "INFO")
        self._refresh_tool_buttons()

    def _on_connect_finished(self, ok: bool, message: str):
        if ok:
            self._connected = True
            if self.main.robot:
                self.main.robot.head = self.head
            self.log(t("log_head_connected"), "SUCCESS")
        else:
            self.log(t("log_head_connect_failed", error=message), "ERROR")
        self._refresh_tool_buttons()

    def check_can_status(self):
        """检查头部 CAN 通道是否已连接/UP。"""
        if not self._ensure_head():
            return
        channel = self.head.can_channel
        is_up = verify_can_interface(channel)
        if is_up:
            if self._connected:
                self.log(t("log_head_can_check_ok_connected", channel=channel), "SUCCESS")
            else:
                self.log(t("log_head_can_check_ok_disconnected", channel=channel), "SUCCESS")
        else:
            if self._connected:
                self._connected = False
                try:
                    self.head.disconnect()
                except Exception:
                    pass
                self._refresh_tool_buttons()
            self.log(t("log_head_can_check_down", channel=channel), "ERROR")

    def enable_motors(self):
        if not self._ensure_head_connected():
            return
        was_monitoring = self.is_monitoring
        if was_monitoring:
            self.is_monitoring = False
            self._monitor_timer.stop()
            if hasattr(self.window, "btn_head_toggle_monitor"):
                self.window.btn_head_toggle_monitor.setText(t("btn_start_monitor"))
        self.log(t("log_head_enabling"), "INFO")
        results, failed = self._enable_motors_sync()
        self._on_enable_finished(results, failed, was_monitoring)

    def _on_enable_finished(self, results: dict, failed: list, resume_monitoring: bool = False):
        if results and not failed:
            self.head.is_enabled = True
            self._joints_need_reenable.clear()
            for motor_id, state in results.items():
                if state == 0:
                    self._hold_joint_position(motor_id)
            self._start_label_refresh()
            self.log(t("log_head_enabled"), "SUCCESS")
            self.sync_status(force=True)
        else:
            self.log(t("log_head_enable_failed", error=""), "ERROR")
            for motor_id, state in (results or {}).items():
                if state == 0:
                    self._joints_need_reenable.discard(motor_id)
        if failed:
            details = getattr(self.head, "_last_enable_errors", {}) if self.head else {}
            for item in failed:
                motor_id = item["motor_id"]
                detail = details.get(motor_id)
                error = f"{item['error']} ({detail})" if detail else item["error"]
                self.log(f"  ID={motor_id}: {error}", "ERROR")
                status = item.get("status")
                if status:
                    mode = status.get("mode_status", "-")
                    fault = status.get("fault_status", "-")
                    angle = status.get("angle")
                    angle_text = (
                        f"{math.degrees(float(angle)):.2f}°"
                        if angle is not None else "-"
                    )
                    self.log(
                        f"  ID={motor_id} 当前状态: mode={mode}, fault={fault}, angle={angle_text}",
                        "ERROR",
                    )
                elif motor_id != -1:
                    self.log(f"  ID={motor_id} 当前状态: 未读到反馈", "ERROR")
        if resume_monitoring:
            self.is_monitoring = True
            interval = int(self.settings.get("head_monitor_interval_ms", 50))
            self._monitor_timer.start(max(30, interval))
            if hasattr(self.window, "btn_head_toggle_monitor"):
                self.window.btn_head_toggle_monitor.setText(t("btn_stop_monitor"))

    def disable_motors(self):
        if not self._ensure_connected():
            return
        self._joint_repeat_timer.stop()
        self.log(t("log_head_disabling"), "INFO")
        try:
            results = self.head.disable(verbose=False)
            failed = [{
                "arm": t("tab_head"),
                "can_channel": self.head.can_channel,
                "motor_id": mid,
                "error": t("motor_disable_failed"),
            } for mid, state in results.items() if state != 0]
            self._on_disable_finished(results, failed)
            if not failed:
                self._refresh_reset_status_before_disconnect()
                self.disconnect_head()
        except Exception as exc:
            self._on_disable_finished({}, [{
                "arm": t("tab_head"),
                "can_channel": self.head.can_channel,
                "motor_id": -1,
                "error": str(exc),
            }])

    def _on_disable_finished(self, _results: dict, failed: list):
        self.head.is_enabled = False
        self._joints_need_reenable.clear()
        self._stop_label_refresh()
        if not failed:
            self.log(t("log_head_disabled_ok"), "SUCCESS")
        else:
            self.log(t("log_head_disable_failed", error=""), "ERROR")

    def _refresh_reset_status_before_disconnect(self) -> None:
        """失能成功后，断开 CAN 前先把界面状态刷成 Reset mode。"""
        if not self.head:
            return
        status = {}
        for mid in self._current_head_motor_ids():
            logical_angle = self._joint_positions.get(mid, 0.0)
            status[mid] = {
                "angle": self.head.to_motor_angle(mid, logical_angle),
                "velocity": 0.0,
                "torque": 0.0,
                "temperature": 0.0,
                "mode_status": "Reset mode",
                "fault_status": "Normal",
            }
        self._update_status_ui(status)

    def set_zero_passive(self, motor_id: int):
        if not self._ensure_head_connected():
            return
        joint = self._joint_label(motor_id)
        was_enabled = bool(self.head and self.head.is_enabled)
        self._apply_immediate_zero_display(motor_id)
        self.log(
            f"{t('log_head_set_zero_start')} [{joint}] ({t('btn_head_zero_manual')})",
            "INFO",
        )
        try:
            state = self.head.set_zero_passive(motor_id=motor_id, verbose=False)
            results = {motor_id: state}
            failed = [] if state == 0 else [{
                "arm": t("tab_head"),
                "can_channel": self.head.can_channel,
                "motor_id": motor_id,
                "error": t("motor_set_zero_failed"),
            }]
            self._on_set_zero_finished(
                motor_id, results, failed, False, joint, was_enabled
            )
        except Exception as exc:
            self._on_set_zero_finished(
                motor_id, {}, [{
                    "arm": t("tab_head"),
                    "can_channel": self.head.can_channel,
                    "motor_id": motor_id,
                    "error": str(exc),
                }], False, joint, was_enabled
            )

    def set_zero_active(self, motor_id: int):
        if not self._ensure_connected():
            return
        joint = self._joint_label(motor_id)
        was_enabled = bool(self.head and self.head.is_enabled)
        self.log(t("log_head_active_zero_warning"), "WARNING")
        self.log(
            f"{t('log_head_set_zero_start')} [{joint}] ({t('btn_head_zero_auto')})",
            "INFO",
        )
        try:
            results = self.head.set_zero_active(motor_id=motor_id, verbose=False)
            info = results.get(motor_id, {})
            failed = [] if info.get("success") else [{
                "arm": t("tab_head"),
                "can_channel": self.head.can_channel,
                "motor_id": motor_id,
                "error": info.get("error", t("motor_set_zero_failed")),
            }]
            self._on_set_zero_finished(
                motor_id, results, failed, True, joint, was_enabled
            )
        except Exception as exc:
            self._on_set_zero_finished(
                motor_id, {}, [{
                    "arm": t("tab_head"),
                    "can_channel": self.head.can_channel,
                    "motor_id": motor_id,
                    "error": str(exc),
                }], True, joint, was_enabled
            )

    def _on_set_zero_finished(
        self,
        motor_id: int,
        _results: dict,
        failed: list,
        active: bool = False,
        joint: str = "",
        reenable_on_next_move: bool = False,
    ):
        mode = t("btn_head_zero_auto") if active else t("btn_head_zero_manual")
        label = joint or self._joint_label(motor_id)
        if not failed:
            self.log(f"{t('log_head_set_zero_success')} [{label}] ({mode})", "SUCCESS")
            self._set_joint_logical_angle(motor_id, 0.0)
            if reenable_on_next_move:
                self._joints_need_reenable.add(motor_id)
            if active:
                self.log(t("log_head_active_zero_reenable"), "WARNING")
        else:
            self.log(f"{t('log_head_set_zero_failed')} [{label}]", "ERROR")
            for item in failed:
                self.log(f"  ID={item['motor_id']}: {item['error']}", "ERROR")
        self.sync_status(force=True)

    def go_home(self, motor_id: int):
        if not self._ensure_connected():
            return
        if motor_id in self._joints_need_reenable:
            try:
                state = self.head.enable_motor_by_id(motor_id, verbose=False)
            except Exception as exc:
                self.log(
                    f"{t('log_head_go_zero_failed')} [{self._joint_label(motor_id)}]: {exc}",
                    "ERROR",
                )
                return
            if state != 0:
                self.log(
                    f"{t('log_head_go_zero_failed')} [{self._joint_label(motor_id)}]",
                    "ERROR",
                )
                return
            self._joints_need_reenable.discard(motor_id)
            self.head.is_enabled = True
            self._hold_joint_at_logical(
                motor_id, self._joint_positions.get(motor_id, 0.0)
            )
        joint = self._joint_label(motor_id)
        self.log(f"{t('log_head_go_zero_start')} [{joint}]", "INFO")
        start_logical = self._joint_positions.get(motor_id, 0.0)
        try:
            result = self.head.go_home(
                motor_id=motor_id,
                verbose=False,
                start_logical=start_logical,
            )
            results = {motor_id: result}
            failed = [] if result == 0 else [{
                "arm": t("tab_head"),
                "can_channel": self.head.can_channel,
                "motor_id": motor_id,
                "error": t("motor_go_zero_failed"),
            }]
            self._on_go_home_finished(motor_id, results, failed, joint)
        except Exception as exc:
            self._on_go_home_finished(
                motor_id, {}, [{
                    "arm": t("tab_head"),
                    "can_channel": self.head.can_channel,
                    "motor_id": motor_id,
                    "error": str(exc),
                }], joint
            )

    def _on_go_home_finished(
        self,
        motor_id: int,
        _results: dict,
        failed: list,
        joint: str = "",
    ):
        label = joint or self._joint_label(motor_id)
        if not failed:
            self.log(f"{t('log_head_go_zero_success')} [{label}]", "SUCCESS")
            self._set_joint_logical_angle(motor_id, 0.0)
            self.head.is_enabled = True
            self._joints_need_reenable.discard(motor_id)
            self._hold_joint_at_logical(motor_id, 0.0)
        else:
            self.log(f"{t('log_head_go_zero_failed')} [{label}]", "ERROR")
        self.sync_status(force=True)

    def sync_status(self, timeout: float = 0.05, force: bool = False):
        """读取头部电机状态并刷新界面（主线程同步）。"""
        del force
        if not self._ensure_connected():
            return
        try:
            with self.head._can_lock:
                status = {
                    mid: self.head.get_motor_status(mid, timeout=timeout)
                    for mid in self.head.motor_ids
                }
            self._update_status_ui(status)
        except Exception as exc:
            self._update_status_ui({"error": str(exc)})

    def check_motors(self):
        for mid in self._current_head_motor_ids():
            self._sync_joint_position_from_motor(mid)
        self.sync_status()
        self.log(t("log_head_checking"), "INFO")

    def _on_joint_pressed(self, motor_id: int, direction: int):
        if not self._ensure_joint_enabled(motor_id):
            return
        self._active_joint = motor_id
        self._active_direction = direction
        self._move_joint_once()
        if not self._joint_repeat_timer.isActive():
            self._joint_repeat_timer.start(100)

    def _on_joint_released(self):
        self._active_joint = None
        self._active_direction = None
        self._joint_repeat_timer.stop()
        self.sync_status(timeout=0.05, force=True)

    def _on_joint_repeat(self):
        if self._active_joint is not None and self._active_direction is not None:
            self._move_joint_once()

    def _move_joint_once(self):
        step_deg = float(self.window.get_head_step_deg())
        delta = math.radians(step_deg * self._active_direction)
        current = self._joint_positions.get(self._active_joint, 0.0)
        target = current + delta
        try:
            target = self.head._clamp_joint_rad(target)
        except Exception:
            pass
        result = self.head.move_to_mit(
            motor_id=self._active_joint,
            position=target,
            wait_response=False,
            timeout=0.05,
        )
        if result == 0:
            self._set_joint_logical_angle(self._active_joint, target)

    def toggle_monitoring(self):
        if not self._ensure_connected():
            return
        if self.is_monitoring:
            self.is_monitoring = False
            self._monitor_timer.stop()
            self.window.btn_head_toggle_monitor.setText(t("btn_start_monitor"))
            self.log(t("log_monitor_stopped"), "INFO")
        else:
            self.is_monitoring = True
            interval = int(self.settings.get("head_monitor_interval_ms", 50))
            self._monitor_timer.start(max(30, interval))
            self.window.btn_head_toggle_monitor.setText(t("btn_stop_monitor"))
            self.log(t("log_monitor_started"), "INFO")
            self.sync_status(force=True)

    def _on_monitor_tick(self):
        if self.is_monitoring:
            self.sync_status()

    def _status_info_for_motor(self, status: dict, motor_id: int) -> dict:
        return status.get(motor_id) or status.get(str(motor_id)) or {}

    def _format_head_mode_cell(self, mode_status_raw: str) -> tuple[str, QColor]:
        mode_status = translate_motor_status(mode_status_raw)
        if "Motor mode" in mode_status_raw or t("motor_mode_motor") in mode_status:
            return f"🟢 {mode_status}", QColor(0, 150, 0)
        if "Reset mode" in mode_status_raw or t("motor_mode_reset") in mode_status:
            return f"🔴 {mode_status}", QColor(200, 0, 0)
        if "Cali mode" in mode_status_raw or t("motor_mode_cali") in mode_status:
            return f"🟡 {mode_status}", QColor(200, 150, 0)
        return f"⚪ {mode_status}", QColor(150, 150, 150)

    def _format_head_fault_cell(self, fault_status_raw: str) -> tuple[str, QColor]:
        fault_status = translate_motor_status(fault_status_raw)
        if fault_status_raw == "Normal" or fault_status == t("motor_fault_normal"):
            return fault_status, QColor(0, 150, 0)
        return fault_status, QColor(200, 0, 0)

    def _build_head_status_row(self, motor_id: int, info: dict) -> list:
        raw_angle = float(info.get("angle", 0.0))
        feedback_angle = self.head.to_logical_angle(motor_id, raw_angle)
        angle = self._joint_positions.get(motor_id, feedback_angle)
        mode_text, mode_color = self._format_head_mode_cell(info.get("mode_status", "-"))
        fault_text, fault_color = self._format_head_fault_cell(info.get("fault_status", "-"))
        joint_key = HEAD_JOINT_LABEL_KEYS.get(motor_id, str(motor_id))
        return [
            ("text", t(joint_key)),
            ("text", self.head.can_channel),
            ("text", str(motor_id)),
            ("text", f"{angle:+.4f} rad ({math.degrees(angle):+.2f}°)"),
            ("text", f"{float(info.get('velocity', 0.0)):+.4f}"),
            ("text", f"{float(info.get('torque', 0.0)):+.4f}"),
            ("temp", f"{float(info.get('temperature', 0.0)):.1f}", float(info.get("temperature", 0.0))),
            ("mode", mode_text, mode_color),
            ("fault", fault_text, fault_color),
        ]

    def _update_status_ui(self, status: dict):
        if "error" in status:
            self.log(f"头部状态读取失败: {status['error']}", "WARNING")
            return
        motor_ids = self._current_head_motor_ids()
        labels = getattr(self.window, "head_joint_value_labels", [])
        for idx, mid in enumerate(motor_ids):
            if idx < len(labels):
                angle = self._joint_positions.get(mid, 0.0)
                labels[idx].setText(f"{math.degrees(angle):.2f}°")
        table = getattr(self.window, "head_table", None)
        if table is None:
            return
        table.setRowCount(len(motor_ids))
        for row, mid in enumerate(motor_ids):
            info = self._status_info_for_motor(status, mid)
            for col, cell in enumerate(self._build_head_status_row(mid, info)):
                if cell[0] == "text":
                    item = QTableWidgetItem(cell[1])
                elif cell[0] == "temp":
                    item = QTableWidgetItem(cell[1])
                    temp = cell[2]
                    if temp > 60:
                        item.setForeground(QColor(200, 0, 0))
                    elif temp > 50:
                        item.setForeground(QColor(200, 150, 0))
                elif cell[0] == "mode":
                    item = QTableWidgetItem(cell[1])
                    item.setForeground(cell[2])
                else:
                    item = QTableWidgetItem(cell[1])
                    item.setForeground(cell[2])
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, col, item)

    def _update_joint_value_label(self, motor_id: int, angle_rad: float):
        labels = getattr(self.window, "head_joint_value_labels", [])
        try:
            idx = self._current_head_motor_ids().index(motor_id)
        except ValueError:
            return
        if idx < len(labels):
            labels[idx].setText(f"{math.degrees(angle_rad):.2f}°")

    def shutdown(self):
        self._monitor_timer.stop()
        self._joint_repeat_timer.stop()
        self._stop_label_refresh()
        if self.head and self._connected:
            try:
                self.head.disconnect()
            except Exception:
                try:
                    self.head.close()
                except Exception:
                    pass
        elif self.head:
            try:
                self.head.close()
            except Exception:
                pass
        self._connected = False
