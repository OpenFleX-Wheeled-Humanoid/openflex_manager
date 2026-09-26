#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
基础功能控制器

负责 CAN 总线管理等基础功能
"""

from PySide6.QtCore import QThread, Signal
from utils.i18n import t
from openflex_driver import (
    enable_all_can_interfaces,
    disable_all_can_interfaces,
    get_all_can_interfaces,
    verify_can_interface,
    enable_can_interface,
    disable_can_interface,
    CAN_DRIVER_KCAN,
)
from ui.can_status_dialog import CANStatusDialog


class _CanWorker(QThread):
    """在子线程中执行CAN操作，通过信号回传日志和结果。"""
    log_signal = Signal(str, str)   # (message, level)
    done_signal = Signal(bool)      # success

    def __init__(self, task, password):
        super().__init__()
        self._task = task
        self._password = password

    def run(self):
        result = self._task(
            log=lambda msg, lvl="INFO": self.log_signal.emit(msg, lvl),
            password=self._password,
        )
        self.done_signal.emit(bool(result))


class BaseController:
    """
    基础功能控制器

    管理 CAN 总线等基础功能
    """

    def __init__(self, main_controller):
        """
        初始化基础功能控制器

        参数:
            main_controller: 主控制器实例，用于访问 window、settings、log 等
        """
        self.main = main_controller
        self.window = main_controller.window
        self.settings = main_controller.settings
        self.log = main_controller.log

        self._can_worker = None  # 持有 worker 引用，防止被 GC

        self._wire_signals()

    @property
    def _sudo_password(self):
        """获取 sudo 密码"""
        return self.settings.get("sudo_password", None)

    @property
    def _can_driver(self):
        """获取 CAN 驱动"""
        return self.settings.get("can_driver", CAN_DRIVER_KCAN)

    def _wire_signals(self):
        """连接信号槽"""
        # CAN 相关按钮
        self.window.btn_start_can.clicked.connect(self.start_can)
        self.window.btn_stop_can.clicked.connect(self.stop_can)
        self.window.btn_check_can.clicked.connect(self.check_can)

    # ==================== CAN 总线管理 ====================

    def _run_can_task(self, task, can_buttons, on_done):
        """在子线程中运行CAN任务，期间禁用相关按钮。"""
        for btn in can_buttons:
            btn.setEnabled(False)

        worker = _CanWorker(task, self._sudo_password)
        worker.log_signal.connect(self.log)
        worker.done_signal.connect(lambda ok: (
            on_done(ok),
            [btn.setEnabled(True) for btn in can_buttons],
        ))
        worker.finished.connect(worker.deleteLater)
        self._can_worker = worker
        worker.start()

    def start_can(self):
        """启动所有 CAN 接口"""
        self.log(t("log_can_starting"), "INFO")
        self._run_can_task(
            task=lambda log, password: enable_all_can_interfaces(
                driver=self._can_driver, verbose=False, log=log, password=password
            ),
            can_buttons=[self.window.btn_start_can, self.window.btn_stop_can, self.window.btn_check_can],
            on_done=lambda ok: self.log(t("log_can_started"), "SUCCESS") if ok else self.log(t("log_can_start_failed"), "ERROR"),
        )

    def stop_can(self):
        """关闭所有 CAN 接口"""
        self.log(t("log_can_stopping"), "INFO")
        self._run_can_task(
            task=lambda log, password: disable_all_can_interfaces(
                verbose=False, log=log, password=password
            ),
            can_buttons=[self.window.btn_start_can, self.window.btn_stop_can, self.window.btn_check_can],
            on_done=lambda ok: self.log(t("log_can_stopped"), "WARNING") if ok else self.log(t("log_can_stop_failed"), "ERROR"),
        )

    def check_can(self):
        """检查 CAN 状态并显示对话框"""
        self.log(t("log_can_checking"), "INFO")

        # 获取所有 CAN 接口
        all_interfaces = get_all_can_interfaces()

        if not all_interfaces:
            self.log(t("log_can_check_none"), "WARNING")
            return

        # 检查每个接口的状态
        can_status_list = []
        for interface in all_interfaces:
            is_up = verify_can_interface(interface)
            can_status_list.append({
                'interface': interface,
                'is_up': is_up
            })

        # 显示对话框
        dialog = CANStatusDialog(self.window)
        dialog.set_can_status_data(can_status_list)

        # 连接信号
        dialog.btn_refresh.clicked.connect(lambda: self._refresh_can_status(dialog))
        dialog.btn_close.clicked.connect(dialog.accept)
        dialog.start_interface_signal.connect(lambda iface: self._start_single_can(iface, dialog))
        dialog.stop_interface_signal.connect(lambda iface: self._stop_single_can(iface, dialog))

        # 记录日志
        up_count = sum(1 for status in can_status_list if status['is_up'])
        self.log(t("log_can_check_result",
                  total=len(can_status_list),
                  up=up_count,
                  down=len(can_status_list) - up_count), "SUCCESS")

        dialog.exec()

    def _refresh_can_status(self, dialog):
        """刷新 CAN 状态"""
        self.log(t("log_can_refreshing"), "INFO")

        # 重新获取状态
        all_interfaces = get_all_can_interfaces()
        can_status_list = []
        for interface in all_interfaces:
            is_up = verify_can_interface(interface)
            can_status_list.append({
                'interface': interface,
                'is_up': is_up
            })

        # 更新对话框
        dialog.set_can_status_data(can_status_list)

        # 记录日志
        up_count = sum(1 for status in can_status_list if status['is_up'])
        self.log(t("log_can_check_result",
                  total=len(can_status_list),
                  up=up_count,
                  down=len(can_status_list) - up_count), "SUCCESS")

    def _start_single_can(self, interface, dialog):
        """启动单个 CAN 接口"""
        self.log(t("log_can_starting_single", interface=interface), "INFO")

        try:
            success = enable_can_interface(
                interface=interface,
                bitrate=1000000,
                driver=self._can_driver,
                verbose=False,
                log=self.log,
                password=self._sudo_password
            )

            if success:
                self.log(t("log_can_started_single", interface=interface), "SUCCESS")
            else:
                self.log(t("log_can_start_failed_single", interface=interface), "ERROR")

        except Exception as e:
            self.log(t("log_can_start_error_single", interface=interface, error=str(e)), "ERROR")

        # 刷新状态
        self._refresh_can_status(dialog)

    def _stop_single_can(self, interface, dialog):
        """关闭单个 CAN 接口"""
        self.log(t("log_can_stopping_single", interface=interface), "INFO")

        try:
            success = disable_can_interface(
                interface=interface,
                verbose=False,
                log=self.log,
                password=self._sudo_password
            )

            if success:
                self.log(t("log_can_stopped_single", interface=interface), "WARNING")
            else:
                self.log(t("log_can_stop_failed_single", interface=interface), "ERROR")

        except Exception as e:
            self.log(t("log_can_stop_error_single", interface=interface, error=str(e)), "ERROR")

        # 刷新状态
        self._refresh_can_status(dialog)
