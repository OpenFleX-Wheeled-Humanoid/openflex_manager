#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
双臂控制器

负责双臂电机的使能、失能、零点设置、运动控制等功能
"""

from PySide6.QtWidgets import QTableWidgetItem, QProgressDialog
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor
from utils.i18n import t
from ui.motor_check_dialog import MotorCheckFailDialog
import math
import time

def translate_motor_status(status_text):
    """
    翻译电机状态文本（从英文翻译成当前语言）

    参数:
        status_text (str): 英文状态文本

    返回:
        str: 翻译后的状态文本
    """
    # 模式状态翻译映射
    mode_translations = {
        "Reset mode": t("motor_mode_reset"),
        "Cali mode": t("motor_mode_cali"),
        "Motor mode": t("motor_mode_motor"),
        "Unknown mode": t("motor_mode_unknown")
    }

    # 故障状态翻译映射
    fault_translations = {
        "Normal": t("motor_fault_normal"),
        "Not calibrated": t("motor_fault_not_calibrated"),
        "Stall overload": t("motor_fault_stall_overload"),
        "Encoder fault": t("motor_fault_encoder"),
        "Overtemp": t("motor_fault_overtemp"),
        "Driver fault": t("motor_fault_driver"),
        "Undervoltage": t("motor_fault_undervoltage")
    }

    # 先检查是否是模式状态
    if status_text in mode_translations:
        return mode_translations[status_text]

    # 检查是否是单个故障状态
    if status_text in fault_translations:
        return fault_translations[status_text]

    # 处理组合故障状态（用逗号分隔）
    if ", " in status_text:
        parts = status_text.split(", ")
        translated_parts = [fault_translations.get(part.strip(), part.strip()) for part in parts]
        return ", ".join(translated_parts)

    # 如果没有匹配，返回原文
    return status_text


class MotorCheckThread(QThread):
    """电机检查后台线程"""

    # 信号：检查完成 (成功的电机状态, 失败的电机列表)
    check_finished = Signal(dict, list)

    def __init__(self, robot):
        super().__init__()
        self.robot = robot

    def run(self):
        """执行电机检查"""
        # 重试机制：如果第一次失败，等待后重试
        # 这解决了CAN接口刚启动时可能还未完全就绪的问题
        max_retries = 3  # 增加到3次重试
        retry_delay = 0.5  # 增加到500ms

        for attempt in range(max_retries):
            try:
                # 获取双臂状态
                arms_status = self.robot.get_arms_status()

                # 收集失败的电机
                failed_motors = []

                # 检查右臂电机
                right_can = self.robot.right_arm.can_channel
                for motor_id in self.robot.right_arm.motor_ids:
                    if motor_id not in arms_status['right'] or not arms_status['right'][motor_id]:
                        failed_motors.append({
                            'arm': t("arm_right_short"),
                            'can_channel': right_can,
                            'motor_id': motor_id,
                            'error': t("motor_fail_no_response")
                        })

                # 检查左臂电机
                left_can = self.robot.left_arm.can_channel
                for motor_id in self.robot.left_arm.motor_ids:
                    if motor_id not in arms_status['left'] or not arms_status['left'][motor_id]:
                        failed_motors.append({
                            'arm': t("arm_left_short"),
                            'can_channel': left_can,
                            'motor_id': motor_id,
                            'error': t("motor_fail_no_response")
                        })

                # 发送完成信号
                self.check_finished.emit(arms_status, failed_motors)
                return  # 成功，退出

            except Exception as e:
                error_msg = str(e)
                # 只针对"网络已关闭"或"Failed to transmit"错误重试
                if ("网络已关闭" in error_msg or "Network is down" in error_msg or
                    "Failed to transmit" in error_msg):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue  # 重试

                # 其他错误或重试次数用尽，发送错误信号
                self.check_finished.emit({}, [{
                    'arm': t("motor_fail_system"),
                    'can_channel': '-',
                    'motor_id': -1,  # 使用-1表示系统级错误
                    'error': error_msg
                }])
                return


class MotorEnableThread(QThread):
    """电机使能后台线程"""

    # 信号：使能完成 (成功的电机字典, 失败的电机列表)
    enable_finished = Signal(dict, list)

    def __init__(self, robot):
        super().__init__()
        self.robot = robot

    def run(self):
        """执行电机使能"""
        # 重试机制：只针对"网络已关闭"错误
        max_retries = 3
        retry_delay = 0.5  # 500ms

        for attempt in range(max_retries):
            try:
                failed_motors = []
                success_results = {}

                result_right = self.robot.right_arm.enable_arm_motors()
                result_left = self.robot.left_arm.enable_arm_motors()

                right_can = self.robot.right_arm.can_channel
                for motor_id, state in result_right.items():
                    if state == 0:
                        success_results[f"right_{motor_id}"] = state
                    else:
                        failed_motors.append({
                            'arm': t("arm_right_short"),
                            'can_channel': right_can,
                            'motor_id': motor_id,
                            'error': t("motor_enable_failed")
                        })

                left_can = self.robot.left_arm.can_channel
                for motor_id, state in result_left.items():
                    if state == 0:
                        success_results[f"left_{motor_id}"] = state
                    else:
                        failed_motors.append({
                            'arm': t("arm_left_short"),
                            'can_channel': left_can,
                            'motor_id': motor_id,
                            'error': t("motor_enable_failed")
                        })

                # 发送完成信号
                self.enable_finished.emit(success_results, failed_motors)
                return  # 成功，退出

            except Exception as e:
                error_msg = str(e)
                # 只针对"网络已关闭"或"Failed to transmit"错误重试
                if ("网络已关闭" in error_msg or "Network is down" in error_msg or
                    "Failed to transmit" in error_msg):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue  # 重试

                # 其他错误或重试次数用尽，发送错误信号
                self.enable_finished.emit({}, [{
                    'arm': t("motor_fail_system"),
                    'can_channel': '-',
                    'motor_id': -1,
                    'error': error_msg
                }])
                return


class MotorDisableThread(QThread):
    """电机失能后台线程"""

    # 信号：失能完成 (成功的电机字典, 失败的电机列表)
    disable_finished = Signal(dict, list)

    def __init__(self, robot):
        super().__init__()
        self.robot = robot

    def run(self):
        """执行电机失能"""
        # 重试机制：只针对"网络已关闭"错误
        max_retries = 3
        retry_delay = 0.5  # 500ms

        for attempt in range(max_retries):
            try:
                failed_motors = []
                success_results = {}

                result_right = self.robot.right_arm.disable_arm_motors()
                result_left = self.robot.left_arm.disable_arm_motors()

                right_can = self.robot.right_arm.can_channel
                for motor_id, state in result_right.items():
                    if state == 0:
                        success_results[f"right_{motor_id}"] = state
                    else:
                        failed_motors.append({
                            'arm': t("arm_right_short"),
                            'can_channel': right_can,
                            'motor_id': motor_id,
                            'error': t("motor_disable_failed")
                        })

                left_can = self.robot.left_arm.can_channel
                for motor_id, state in result_left.items():
                    if state == 0:
                        success_results[f"left_{motor_id}"] = state
                    else:
                        failed_motors.append({
                            'arm': t("arm_left_short"),
                            'can_channel': left_can,
                            'motor_id': motor_id,
                            'error': t("motor_disable_failed")
                        })

                # 发送完成信号
                self.disable_finished.emit(success_results, failed_motors)
                return  # 成功，退出

            except Exception as e:
                error_msg = str(e)
                # 只针对"网络已关闭"或"Failed to transmit"错误重试
                if ("网络已关闭" in error_msg or "Network is down" in error_msg or
                    "Failed to transmit" in error_msg):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue  # 重试

                # 其他错误或重试次数用尽，发送错误信号
                self.disable_finished.emit({}, [{
                    'arm': t("motor_fail_system"),
                    'can_channel': '-',
                    'motor_id': -1,
                    'error': error_msg
                }])
                return


class SetZeroThread(QThread):
    """设置零点后台线程"""

    # 信号：设置完成 (成功数, 失败的电机列表)
    set_zero_finished = Signal(int, list)

    def __init__(self, robot):
        super().__init__()
        self.robot = robot

    def run(self):
        """执行设置零点"""
        try:
            failed_motors = []
            success_count = 0

            # 设置右臂零点（不输出详细日志，避免线程安全问题）
            right_failed_count = self.robot.set_zero_right_arm(verbose=False)
            right_can = self.robot.right_arm.can_channel

            # 检查右臂哪些电机失败了
            if right_failed_count > 0:
                # 由于 set_zero_right_arm 只返回失败数量，我们需要逐个检查
                # 这里简化处理：假设前 right_failed_count 个电机失败
                for i, motor_id in enumerate(self.robot.right_arm.motor_ids):
                    if i < right_failed_count:
                        failed_motors.append({
                            'arm': t("arm_right_short"),
                            'can_channel': right_can,
                            'motor_id': motor_id,
                            'error': t("motor_set_zero_failed")
                        })
                    else:
                        success_count += 1
            else:
                success_count += len(self.robot.right_arm.motor_ids)

            # 设置左臂零点（不输出详细日志，避免线程安全问题）
            left_failed_count = self.robot.set_zero_left_arm(verbose=False)
            left_can = self.robot.left_arm.can_channel

            # 检查左臂哪些电机失败了
            if left_failed_count > 0:
                for i, motor_id in enumerate(self.robot.left_arm.motor_ids):
                    if i < left_failed_count:
                        failed_motors.append({
                            'arm': t("arm_left_short"),
                            'can_channel': left_can,
                            'motor_id': motor_id,
                            'error': t("motor_set_zero_failed")
                        })
                    else:
                        success_count += 1
            else:
                success_count += len(self.robot.left_arm.motor_ids)

            # 发送完成信号
            self.set_zero_finished.emit(success_count, failed_motors)

        except Exception as e:
            # 发送错误信号（所有电机都失败）
            failed_motors = []
            right_can = self.robot.right_arm.can_channel
            left_can = self.robot.left_arm.can_channel

            for motor_id in self.robot.right_arm.motor_ids:
                failed_motors.append({
                    'arm': t("arm_right_short"),
                    'can_channel': right_can,
                    'motor_id': motor_id,
                    'error': str(e)
                })

            for motor_id in self.robot.left_arm.motor_ids:
                failed_motors.append({
                    'arm': t("arm_left_short"),
                    'can_channel': left_can,
                    'motor_id': motor_id,
                    'error': str(e)
                })

            self.set_zero_finished.emit(0, failed_motors)


class GoZeroThread(QThread):
    """回零后台线程"""

    # 信号：回零完成 (成功数, 失败的电机列表)
    go_zero_finished = Signal(int, list)

    def __init__(self, robot):
        super().__init__()
        self.robot = robot

    def run(self):
        """执行MIT回零"""
        try:
            failed_motors = []
            success_count = 0

            # 右臂MIT回零（不输出详细日志，避免线程安全问题）
            right_results = self.robot.go_home_mit_right_arm(verbose=False) 
            right_can = self.robot.right_arm.can_channel

            # 检查右臂哪些电机失败了
            for motor_id, state in right_results.items():
                if state == 0:
                    success_count += 1
                else:
                    failed_motors.append({
                        'arm': t("arm_right_short"),
                        'can_channel': right_can,
                        'motor_id': motor_id,
                        'error': t("motor_go_zero_failed")
                    })

            # 左臂MIT回零（不输出详细日志，避免线程安全问题）
            left_results = self.robot.go_home_mit_left_arm(verbose=False)
            left_can = self.robot.left_arm.can_channel

            # 检查左臂哪些电机失败了
            for motor_id, state in left_results.items():
                if state == 0:
                    success_count += 1
                else:
                    failed_motors.append({
                        'arm': t("arm_left_short"),
                        'can_channel': left_can,
                        'motor_id': motor_id,
                        'error': t("motor_go_zero_failed")
                    })

            # 发送完成信号
            self.go_zero_finished.emit(success_count, failed_motors)

        except Exception as e:
            # 发送错误信号（所有电机都失败）
            failed_motors = []
            right_can = self.robot.right_arm.can_channel
            left_can = self.robot.left_arm.can_channel

            for motor_id in self.robot.right_arm.motor_ids:
                failed_motors.append({
                    'arm': t("arm_right_short"),
                    'can_channel': right_can,
                    'motor_id': motor_id,
                    'error': str(e)
                })

            for motor_id in self.robot.left_arm.motor_ids:
                failed_motors.append({
                    'arm': t("arm_left_short"),
                    'can_channel': left_can,
                    'motor_id': motor_id,
                    'error': str(e)
                })

            self.go_zero_finished.emit(0, failed_motors)


class TestAllMotorsThread(QThread):
    """测试所有电机后台线程"""

    # 信号：测试完成 (测试结果字典)
    test_finished = Signal(dict)

    def __init__(self, robot, position_max=0.2, kp=10.0, kd=1.0, duration=0.5):
        super().__init__()
        self.robot = robot
        self.position_max = position_max
        self.kp = kp
        self.kd = kd
        self.duration = duration

    def run(self):
        """执行电机测试"""
        try:
            # 调用robot的test_motors_one_by_one方法
            results = self.robot.test_motors_one_by_one(
                right_positions=[self.position_max] * 8,
                left_positions=[self.position_max] * 8,
                kp=self.kp,
                kd=self.kd,
                duration=self.duration,
                verbose=False  # 不输出详细日志，避免线程安全问题
            )

            # 发送完成信号
            self.test_finished.emit(results)

        except Exception as e:
            # 发送错误信号
            results = {
                'right_arm': {mid: 1 for mid in self.robot.right_arm.motor_ids},
                'left_arm': {mid: 1 for mid in self.robot.left_arm.motor_ids},
                'error': str(e)
            }
            self.test_finished.emit(results)


class ArmController:
    """
    双臂控制器

    管理双臂电机的使能、失能、零点、运动控制等功能
    """

    def __init__(self, main_controller):
        """
        初始化双臂控制器

        参数:
            main_controller: 主控制器实例，用于访问 window、robot、log 等
        """
        self.main = main_controller
        self.window = main_controller.window
        self.robot = main_controller.robot
        self.log = main_controller.log

        # 实时监控定时器
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self._update_motor_status)
        self.is_monitoring = False

        # 保存最后一次获取的电机状态，用于切换控制目标时更新角度显示
        self.last_arms_status = None

        # 长按控制定时器
        self.long_press_timer = QTimer()
        self.long_press_timer.timeout.connect(self._on_long_press_repeat)
        self.long_press_joint_index = None
        self.long_press_direction = None  # 1 for plus, -1 for minus

        self._wire_signals()

    def _wire_signals(self):
        """连接信号槽"""
        # 电机使能/失能
        self.window.btn_enable_arm.clicked.connect(self.enable_motors)
        self.window.btn_disable_arm.clicked.connect(self.disable_motors)

        # 零点设置
        self.window.btn_set_zero_arm.clicked.connect(self.set_zero)
        self.window.btn_go_zero_arm.clicked.connect(self.go_zero)

        # 电机测试
        self.window.btn_test_all_motors.clicked.connect(self.test_all_motors)
        self.window.btn_one_click_check.clicked.connect(self.check_motor_status)

        # 实时监控
        self.window.btn_toggle_monitor.clicked.connect(self.toggle_monitoring)

        # 步长滑轨和数值框的双向同步
        self.window.slider_speed.valueChanged.connect(self._update_step_spinbox_from_slider)
        self.window.spinbox_step.valueChanged.connect(self._update_step_slider_from_spinbox)

        # 控制目标切换时更新关节角度显示
        self.window.arm_target_combo.currentIndexChanged.connect(self._on_arm_target_changed)

        # 关节控制按钮
        for joint_index, btn_minus, _, btn_plus in self.window.joint_rows:
            # 减号按钮
            btn_minus.pressed.connect(
                lambda idx=joint_index: self._on_joint_button_pressed(idx, -1)
            )
            btn_minus.released.connect(self._on_joint_button_released)

            # 加号按钮
            btn_plus.pressed.connect(
                lambda idx=joint_index: self._on_joint_button_pressed(idx, 1)
            )
            btn_plus.released.connect(self._on_joint_button_released)

    # ==================== 电机使能/失能 ====================

    def enable_motors(self):
        """使能电机"""
        # 立即显示开始日志
        arm_name = self.window.get_selected_arm_display_name()
        self.log(t("log_motor_enabling", arm=arm_name), "INFO")

        if not self.robot:
            self.log("Robot 未初始化", "ERROR")
            return

        # 创建加载对话框
        self.enable_progress_dialog = QProgressDialog(
            t("dialog_motor_enabling"),
            "",  # 不显示取消按钮
            0, 0,  # 不确定进度
            self.window
        )
        self.enable_progress_dialog.setWindowTitle(t("dialog_motor_enabling_title"))
        self.enable_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.enable_progress_dialog.setCancelButton(None)  # 禁用取消按钮
        self.enable_progress_dialog.setMinimumDuration(0)  # 立即显示
        self.enable_progress_dialog.show()

        # 创建并启动使能线程
        self.enable_thread = MotorEnableThread(self.robot)
        self.enable_thread.enable_finished.connect(self._on_enable_finished)
        self.enable_thread.start()

    def _on_enable_finished(self, success_results, failed_motors):
        """使能完成回调"""
        # 关闭加载对话框
        if hasattr(self, 'enable_progress_dialog'):
            self.enable_progress_dialog.close()
            delattr(self, 'enable_progress_dialog')

        arm_name = self.window.get_selected_arm_display_name()
        success_count = len(success_results)

        if success_count > 0:
            self.log(t("log_motor_enabled_success", arm=arm_name, count=success_count), "SUCCESS")
        else:
            self.log(t("log_motor_enabled_all_failed", arm=arm_name), "ERROR")

        # 如果有失败的电机，显示错误对话框
        if failed_motors:
            fail_dialog = MotorCheckFailDialog(failed_motors, self.window)
            fail_dialog.exec()

        self._refresh_status_after_power_change()

    def disable_motors(self):
        """失能电机"""
        # 立即显示开始日志
        arm_name = self.window.get_selected_arm_display_name()
        self.log(t("log_motor_disabling", arm=arm_name), "INFO")

        if not self.robot:
            self.log("Robot 未初始化", "ERROR")
            return

        # 创建加载对话框
        self.disable_progress_dialog = QProgressDialog(
            t("dialog_motor_disabling"),
            "",  # 不显示取消按钮
            0, 0,  # 不确定进度
            self.window
        )
        self.disable_progress_dialog.setWindowTitle(t("dialog_motor_disabling_title"))
        self.disable_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.disable_progress_dialog.setCancelButton(None)  # 禁用取消按钮
        self.disable_progress_dialog.setMinimumDuration(0)  # 立即显示
        self.disable_progress_dialog.show()

        # 创建并启动失能线程
        self.disable_thread = MotorDisableThread(self.robot)
        self.disable_thread.disable_finished.connect(self._on_disable_finished)
        self.disable_thread.start()

    def _on_disable_finished(self, success_results, failed_motors):
        """失能完成回调"""
        # 关闭加载对话框
        if hasattr(self, 'disable_progress_dialog'):
            self.disable_progress_dialog.close()
            delattr(self, 'disable_progress_dialog')

        arm_name = self.window.get_selected_arm_display_name()
        success_count = len(success_results)

        if success_count > 0:
            self.log(t("log_motor_disabled_success", arm=arm_name, count=success_count), "SUCCESS")
        else:
            self.log(t("log_motor_disabled_all_failed", arm=arm_name), "ERROR")

        # 如果有失败的电机，显示错误对话框
        if failed_motors:
            fail_dialog = MotorCheckFailDialog(failed_motors, self.window)
            fail_dialog.exec()

        self._refresh_status_after_power_change()

    def _refresh_status_after_power_change(self):
        """使能/失能后刷新状态面板，确保模式列显示最新反馈。"""
        self.check_motor_status()

    # ==================== 零点设置 ====================

    def set_zero(self):
        """设定零点（双臂）"""
        if not self.robot:
            self.log(t("log_robot_not_initialized"), "ERROR")
            return

        # 立即显示开始日志
        self.log(t("log_set_zero_start_both"), "INFO")

        # 创建加载对话框
        self.set_zero_progress_dialog = QProgressDialog(
            t("dialog_set_zero_progress_both"),
            "",  # 不显示取消按钮
            0, 0,  # 不确定进度
            self.window
        )
        self.set_zero_progress_dialog.setWindowTitle(t("dialog_set_zero_title"))
        self.set_zero_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.set_zero_progress_dialog.setCancelButton(None)  # 禁用取消按钮
        self.set_zero_progress_dialog.setMinimumDuration(0)  # 立即显示
        self.set_zero_progress_dialog.show()

        # 创建并启动设置零点线程
        self.set_zero_thread = SetZeroThread(self.robot)
        self.set_zero_thread.set_zero_finished.connect(self._on_set_zero_finished)
        self.set_zero_thread.start()

    def _on_set_zero_finished(self, success_count, failed_motors):
        """设置零点完成回调"""
        # 关闭加载对话框
        if hasattr(self, 'set_zero_progress_dialog'):
            self.set_zero_progress_dialog.close()
            delattr(self, 'set_zero_progress_dialog')

        # 统计失败的电机
        total_failed = len(failed_motors)

        if total_failed == 0:
            self.log(t("log_set_zero_success_both"), "SUCCESS")
        else:
            self.log(t("log_set_zero_partial_both", failed=total_failed), "ERROR")

        # 如果有失败的电机，显示错误对话框
        if failed_motors:
            fail_dialog = MotorCheckFailDialog(failed_motors, self.window)
            fail_dialog.exec()

        # 自动刷新电机状态，让用户看到零点变化
        self.log(t("log_one_click_start"), "INFO")
        self.check_motor_status()

    def go_zero(self):
        """回零（MIT模式，双臂）"""
        if not self.robot:
            self.log(t("log_robot_not_initialized"), "ERROR")
            return

        # 立即显示开始日志
        self.log(t("log_go_zero_start_both"), "INFO")

        # 创建加载对话框
        self.go_zero_progress_dialog = QProgressDialog(
            t("dialog_go_zero_progress_both"),
            "",  # 不显示取消按钮
            0, 0,  # 不确定进度
            self.window
        )
        self.go_zero_progress_dialog.setWindowTitle(t("dialog_go_zero_title"))
        self.go_zero_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.go_zero_progress_dialog.setCancelButton(None)  # 禁用取消按钮
        self.go_zero_progress_dialog.setMinimumDuration(0)  # 立即显示
        self.go_zero_progress_dialog.show()

        # 创建并启动回零线程
        self.go_zero_thread = GoZeroThread(self.robot)
        self.go_zero_thread.go_zero_finished.connect(self._on_go_zero_finished)
        self.go_zero_thread.start()

    def _on_go_zero_finished(self, success_count, failed_motors):
        """回零完成回调"""
        # 关闭加载对话框
        if hasattr(self, 'go_zero_progress_dialog'):
            self.go_zero_progress_dialog.close()
            delattr(self, 'go_zero_progress_dialog')

        # 统计失败的电机
        total_failed = len(failed_motors)
        total_motors = success_count + total_failed

        if total_failed == 0:
            self.log(t("log_go_zero_success_both", total=total_motors), "SUCCESS")
        else:
            self.log(t("log_go_zero_partial_both", failed=total_failed, success=success_count, total=total_motors), "ERROR")

        # 如果有失败的电机，显示错误对话框
        if failed_motors:
            fail_dialog = MotorCheckFailDialog(failed_motors, self.window)
            fail_dialog.exec()

        # 自动刷新电机状态，让用户看到回零后的位置变化
        self.log(t("log_one_click_start"), "INFO")
        self.check_motor_status()

    # ==================== 电机测试 ====================

    def test_all_motors(self):
        """测试所有电机（逐个运动并回零）"""
        if not self.robot:
            self.log(t("log_robot_not_initialized"), "ERROR")
            return

        # 立即显示开始日志
        self.log(t("log_test_all_motors_start", arm="双臂"), "INFO")

        # 创建加载对话框
        self.test_progress_dialog = QProgressDialog(
            t("dialog_test_motors_progress"),
            "",  # 不显示取消按钮
            0, 0,  # 不确定进度
            self.window
        )
        self.test_progress_dialog.setWindowTitle(t("dialog_test_motors_title"))
        self.test_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.test_progress_dialog.setCancelButton(None)  # 禁用取消按钮
        self.test_progress_dialog.setMinimumDuration(0)  # 立即显示
        self.test_progress_dialog.show()

        # 创建并启动测试线程
        self.test_thread = TestAllMotorsThread(
            robot=self.robot,
            position_max=0.2,  # 最大运动角度（弧度）
            kp=10.0,
            kd=1.0,
            duration=0.5
        )
        self.test_thread.test_finished.connect(self._on_test_finished)
        self.test_thread.start()

    def _on_test_finished(self, results):
        """测试完成回调"""
        # 关闭加载对话框
        if hasattr(self, 'test_progress_dialog'):
            self.test_progress_dialog.close()
            delattr(self, 'test_progress_dialog')

        # 检查是否有错误
        if 'error' in results:
            self.log(f"电机测试失败: {results['error']}", "ERROR")
            return

        # 统计结果
        total_motors = 0
        total_success = 0
        total_failed = 0
        failed_motors = []

        for arm_name, arm_results in results.items():
            if arm_name == 'error':
                continue

            arm_display = t("arm_right_short") if arm_name == 'right_arm' else t("arm_left_short")
            can_channel = self.robot.right_arm.can_channel if arm_name == 'right_arm' else self.robot.left_arm.can_channel

            for motor_id, state in arm_results.items():
                total_motors += 1
                if state == 0:
                    total_success += 1
                else:
                    total_failed += 1
                    failed_motors.append({
                        'arm': arm_display,
                        'can_channel': can_channel,
                        'motor_id': motor_id,
                        'error': t("motor_test_failed")
                    })

        # 显示结果日志
        if total_failed == 0:
            self.log(t("log_test_all_motors_success", total=total_motors), "SUCCESS")
        else:
            self.log(t("log_test_all_motors_partial", success=total_success, failed=total_failed, total=total_motors), "WARNING")

        # 如果有失败的电机，显示错误对话框
        if failed_motors:
            fail_dialog = MotorCheckFailDialog(failed_motors, self.window)
            fail_dialog.exec()

        # 自动刷新电机状态，让用户看到测试后的位置
        self.log(t("log_one_click_start"), "INFO")
        self.check_motor_status()

    # ==================== 实时监控 ====================

    def toggle_monitoring(self):
        """切换实时监控状态"""
        if self.is_monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        """启动实时监控"""
        if not self.robot:
            self.log("Robot 未初始化", "ERROR")
            return

        if not self.is_monitoring:
            self.is_monitoring = True
            self.monitor_timer.start(100)  # 100ms 更新间隔
            self.window.btn_toggle_monitor.setText(t("btn_stop_monitor"))
            self.log(t("log_monitor_started"), "INFO")

    def stop_monitoring(self):
        """停止实时监控"""
        if self.is_monitoring:
            self.is_monitoring = False
            self.monitor_timer.stop()
            self.window.btn_toggle_monitor.setText(t("btn_start_monitor"))
            self.log(t("log_monitor_stopped"), "INFO")

    def _update_motor_status(self):
        """定时更新电机状态（实时监控）"""
        if not self.robot or not self.is_monitoring:
            return

        try:
            # 获取双臂状态
            arms_status = self.robot.get_arms_status()

            # 清空表格
            self.window.motor_table.setRowCount(0)

            # 获取 CAN 通道信息
            right_can = self.robot.right_arm.can_channel
            left_can = self.robot.left_arm.can_channel

            row = 0

            # 添加右臂电机状态
            for motor_id in sorted(arms_status['right'].keys()):
                status = arms_status['right'][motor_id]
                if status:
                    self._add_motor_row(row, t("arm_right_short"), right_can, motor_id, status)
                    row += 1

            # 添加左臂电机状态
            for motor_id in sorted(arms_status['left'].keys()):
                status = arms_status['left'][motor_id]
                if status:
                    self._add_motor_row(row, t("arm_left_short"), left_can, motor_id, status)
                    row += 1

            # 保存电机状态用于切换控制目标时更新
            self.last_arms_status = arms_status

            # 更新关节角度显示
            self._update_joint_angles(arms_status)

        except Exception as e:
            self.log(f"实时监控更新失败: {str(e)}", "ERROR")
            self.stop_monitoring()

    def check_motor_status(self):
        """检查电机状态并更新到表格"""
        # 立即显示开始日志
        self.log(t("log_one_click_start"), "INFO")

        if not self.robot:
            self.log("Robot 未初始化", "ERROR")
            return

        # 创建加载对话框
        self.progress_dialog = QProgressDialog(
            t("dialog_motor_checking"),
            "",  # 不显示取消按钮
            0, 0,  # 不确定进度
            self.window
        )
        self.progress_dialog.setWindowTitle(t("dialog_motor_checking_title"))
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setCancelButton(None)  # 禁用取消按钮
        self.progress_dialog.setMinimumDuration(0)  # 立即显示
        self.progress_dialog.show()

        # 创建并启动检查线程
        self.check_thread = MotorCheckThread(self.robot)
        self.check_thread.check_finished.connect(self._on_check_finished)
        self.check_thread.start()

    def _on_check_finished(self, arms_status, failed_motors):
        """检查完成回调"""
        # 关闭加载对话框
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
            delattr(self, 'progress_dialog')

        try:
            # 清空表格
            self.window.motor_table.setRowCount(0)

            # 获取 CAN 通道信息
            right_can = self.robot.right_arm.can_channel
            left_can = self.robot.left_arm.can_channel

            row = 0

            # 添加右臂电机状态
            for motor_id in sorted(arms_status.get('right', {}).keys()):
                status = arms_status['right'][motor_id]
                if status:
                    self._add_motor_row(row, t("arm_right_short"), right_can, motor_id, status)
                    row += 1

            # 添加左臂电机状态
            for motor_id in sorted(arms_status.get('left', {}).keys()):
                status = arms_status['left'][motor_id]
                if status:
                    self._add_motor_row(row, t("arm_left_short"), left_can, motor_id, status)
                    row += 1

            online_count = row
            self.log(t("log_one_click_done_with_count", count=online_count), "SUCCESS")

            # 保存电机状态用于切换控制目标时更新
            self.last_arms_status = arms_status

            # 更新关节角度显示
            self._update_joint_angles(arms_status)

            # 如果有失败的电机，显示错误对话框
            if failed_motors:
                if '网络已关闭' in failed_motors[0]['error']:
                    return
                else:
                    fail_dialog = MotorCheckFailDialog(failed_motors, self.window)
                    fail_dialog.exec()

        except Exception as e:
            self.log(f"检查电机状态失败: {str(e)}", "ERROR")

    def _add_motor_row(self, row, arm_name, can_channel, motor_id, status):
        """
        添加一行电机状态到表格

        参数:
            row (int): 行号
            arm_name (str): 臂名称（左臂/右臂）
            can_channel (str): CAN 通道（can0/can1）
            motor_id (int): 电机 ID
            status (dict): 电机状态信息
        """
        self.window.motor_table.insertRow(row)

        # 列 0: CAN 通道（显示为"右臂 (can0)"或"左臂 (can1)"）
        can_text = f"{arm_name} ({can_channel})"
        can_item = QTableWidgetItem(can_text)
        can_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window.motor_table.setItem(row, 0, can_item)

        # 列 1: 电机 ID
        id_item = QTableWidgetItem(str(motor_id))
        id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window.motor_table.setItem(row, 1, id_item)

        # 列 2: 位置 (rad)
        angle = status.get('angle', 0.0)
        angle_item = QTableWidgetItem(f"{angle:.3f}")
        angle_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window.motor_table.setItem(row, 2, angle_item)

        # 列 3: 速度 (rad/s)
        velocity = status.get('velocity', 0.0)
        velocity_item = QTableWidgetItem(f"{velocity:.3f}")
        velocity_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window.motor_table.setItem(row, 3, velocity_item)

        # 列 4: 扭矩 (Nm)
        torque = status.get('torque', 0.0)
        torque_item = QTableWidgetItem(f"{torque:.3f}")
        torque_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window.motor_table.setItem(row, 4, torque_item)

        # 列 5: 温度 (C)
        temperature = status.get('temperature', 0.0)
        temp_item = QTableWidgetItem(f"{temperature:.1f}")
        temp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        # 温度过高时标红
        if temperature > 60:
            temp_item.setForeground(QColor(200, 0, 0))  # 红色
        elif temperature > 50:
            temp_item.setForeground(QColor(200, 150, 0))  # 橙色
        self.window.motor_table.setItem(row, 5, temp_item)

        # 列 6: 模式
        mode_status_raw = status.get('mode_status', '未知')
        mode_status = translate_motor_status(mode_status_raw)

        # 根据模式添加图标
        if 'Motor mode' in mode_status_raw or t("motor_mode_motor") in mode_status:
            mode_icon = "🟢"
            mode_color = QColor(0, 150, 0)  # 绿色
        elif 'Reset mode' in mode_status_raw or t("motor_mode_reset") in mode_status:
            mode_icon = "🔴"
            mode_color = QColor(200, 0, 0)  # 红色
        elif 'Cali mode' in mode_status_raw or t("motor_mode_cali") in mode_status:
            mode_icon = "🟡"
            mode_color = QColor(200, 150, 0)  # 黄色
        else:
            mode_icon = "⚪"
            mode_color = QColor(150, 150, 150)  # 灰色

        mode_item = QTableWidgetItem(f"{mode_icon} {mode_status}")
        mode_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        mode_item.setForeground(mode_color)
        self.window.motor_table.setItem(row, 6, mode_item)

        # 列 7: 状态
        fault_status_raw = status.get('fault_status', '未知')
        fault_status = translate_motor_status(fault_status_raw)
        status_item = QTableWidgetItem(fault_status)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        # 根据故障状态设置颜色
        if fault_status_raw == "Normal" or fault_status == t("motor_fault_normal"):
            status_item.setForeground(QColor(0, 150, 0))  # 绿色
        else:
            status_item.setForeground(QColor(200, 0, 0))  # 红色
        self.window.motor_table.setItem(row, 7, status_item)

    def _update_joint_angles(self, arms_status):
        """
        更新关节角度显示

        参数:
            arms_status (dict): 电机状态信息，格式为 {'right': {motor_id: status}, 'left': {motor_id: status}}
        """
        import math

        # 获取当前选择的臂
        arm_code = self.window.get_selected_arm_code()

        # 根据选择的臂获取对应的电机状态
        if arm_code == "R":
            motor_status = arms_status.get('right', {})
        elif arm_code == "L":
            motor_status = arms_status.get('left', {})
        else:
            return

        # 更新每个关节的角度显示（电机ID 1-8 对应关节索引 0-7）
        for motor_id in range(1, 9):
            joint_index = motor_id - 1
            if motor_id in motor_status and motor_status[motor_id]:
                status = motor_status[motor_id]
                angle_rad = status.get('angle', 0.0)
                # 弧度转角度
                angle_deg = math.degrees(angle_rad)
                # 更新显示
                _, _, value_label, _ = self.window.joint_rows[joint_index]
                value_label.setText(f"{angle_deg:.2f}°")
            else:
                # 如果电机没有响应，显示为未知
                _, _, value_label, _ = self.window.joint_rows[joint_index]
                value_label.setText("--")

    # ==================== 关节控制 ====================

    def _on_arm_target_changed(self):
        """控制目标切换时更新关节角度显示"""
        if hasattr(self, 'last_arms_status') and self.last_arms_status:
            self._update_joint_angles(self.last_arms_status)
        else:
            # 如果还没有获取过电机状态，显示为未知
            for joint_index in range(8):
                _, _, value_label, _ = self.window.joint_rows[joint_index]
                value_label.setText("--")

    def _update_step_spinbox_from_slider(self, value):
        """滑轨变化时更新步长数值框"""
        # 将滑轨值 (0-100) 映射到步长值 (0.0-10.0)
        step_value = value / 10.0
        self.window.spinbox_step.blockSignals(True)
        self.window.spinbox_step.setValue(step_value)
        self.window.spinbox_step.blockSignals(False)

    def _update_step_slider_from_spinbox(self, value):
        """步长数值框变化时更新滑轨"""
        # 将步长值 (0.0-10.0) 映射到滑轨值 (0-100)
        slider_value = int(value * 10)
        self.window.slider_speed.blockSignals(True)
        self.window.slider_speed.setValue(slider_value)
        self.window.slider_speed.blockSignals(False)

    def move_joint_minus(self, joint_index):
        """关节反向调节"""
        joint_name = self.window.get_joint_display_name(joint_index)
        self.log(t("log_joint_minus", joint=joint_name), "INFO")
        self._move_joint_by_step(joint_index, -1)

    def move_joint_plus(self, joint_index):
        """关节正向调节"""
        joint_name = self.window.get_joint_display_name(joint_index)
        self.log(t("log_joint_plus", joint=joint_name), "INFO")
        self._move_joint_by_step(joint_index, 1)

    def _on_joint_button_pressed(self, joint_index, direction):
        """关节按钮按下时触发"""
        # 立即执行一次移动
        self._move_joint_by_step(joint_index, direction)

        # 保存长按信息
        self.long_press_joint_index = joint_index
        self.long_press_direction = direction

        # 启动长按定时器（500ms 后开始连续移动）
        self.long_press_timer.start(500)

    def _on_joint_button_released(self):
        """关节按钮释放时触发"""
        # 停止长按定时器
        self.long_press_timer.stop()
        self.long_press_joint_index = None
        self.long_press_direction = None

    def _on_long_press_repeat(self):
        """长按重复触发"""
        if self.long_press_joint_index is not None and self.long_press_direction is not None:
            self._move_joint_by_step(self.long_press_joint_index, self.long_press_direction)
            # 切换到更快的重复间隔（100ms）
            if self.long_press_timer.interval() != 100:
                self.long_press_timer.setInterval(100)

    def _move_joint_by_step(self, joint_index, direction):
        """
        按步长移动关节

        参数:
            joint_index (int): 关节索引 (0-7)
            direction (int): 方向，1 为正向，-1 为反向
        """

        if not self.robot:
            self.log("Robot 未初始化", "ERROR")
            return

        # 获取步长（角度）
        step_deg = self.window.spinbox_step.value()
        step_rad = math.radians(step_deg * direction)

        # 获取当前选择的臂
        arm_code = self.window.get_selected_arm_code()

        # 电机 ID = 关节索引 + 1
        motor_id = joint_index + 1

        # 获取当前角度
        current_angle_rad = 0.0
        if self.last_arms_status:
            arm_key = 'right' if arm_code == "R" else 'left'
            motor_status = self.last_arms_status.get(arm_key, {})
            if motor_id in motor_status and motor_status[motor_id]:
                current_angle_rad = motor_status[motor_id].get('angle', 0.0)

        # 计算目标角度
        target_angle_rad = current_angle_rad + step_rad

        # 使用 robot 的 MIT 模式移动到目标位置
        try:
            if arm_code == "R":
                result = self.robot.move_to_mit_right_arm(
                    motor_id=motor_id,
                    position=target_angle_rad,
                    velocity=0.0,
                    torque=0.0,
                    kp=10.0,
                    kd=1.0,
                    wait_response=False,
                    verbose=False
                )
            elif arm_code == "L":
                result = self.robot.move_to_mit_left_arm(
                    motor_id=motor_id,
                    position=target_angle_rad,
                    velocity=0.0,
                    torque=0.0,
                    kp=10.0,
                    kd=1.0,
                    wait_response=False,
                    verbose=False
                )
            else:
                self.log("无效的控制目标", "ERROR")
                return

            if result == 0:
                # 更新本地缓存的角度值
                if self.last_arms_status:
                    arm_key = 'right' if arm_code == "R" else 'left'
                    if arm_key in self.last_arms_status:
                        if motor_id not in self.last_arms_status[arm_key]:
                            self.last_arms_status[arm_key][motor_id] = {}
                        self.last_arms_status[arm_key][motor_id]['angle'] = target_angle_rad

                # 更新显示
                _, _, value_label, _ = self.window.joint_rows[joint_index]
                value_label.setText(f"{math.degrees(target_angle_rad):.2f}°")
        except Exception as e:
            self.log(f"电机控制失败: {str(e)}", "ERROR")
