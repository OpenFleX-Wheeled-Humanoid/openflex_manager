#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
主控制器

作为入口，协调各个子控制器，管理 Robot 实例
"""

from utils.settings import SettingsManager
from utils.i18n import t
from openflex_driver.robot import Robot

# 导入子控制器
from .base_controller import BaseController
from .arm_controller import ArmController
from .chassis_controller import ChassisController
from .column_controller import ColumnController
from .head_controller import HeadController
from .ui_controller import UIController


class MainController:
    """
    主控制器

    作为入口，协调各个子控制器，管理核心业务对象（Robot）
    """

    def __init__(self, window):
        """
        初始化主控制器

        参数:
            window: 主窗口实例
        """
        self.window = window
        self.settings = SettingsManager()
        self.robot = None  # Robot 实例，软件的核心业务对象

        # 初始化子控制器（顺序很重要：UI 控制器需要先初始化，因为其他控制器需要 log 方法）
        self.ui_controller = UIController(self)
        self.base_controller = BaseController(self)
        self.arm_controller = ArmController(self)
        self.chassis_controller = ChassisController(self)
        self.column_controller = ColumnController(self)
        self.head_controller = HeadController(self)

        # 初始化表格和 Robot
        self._seed_table()
        self._initialize_robot()

    @property
    def log(self):
        """日志方法（委托给 UI 控制器）"""
        return self.ui_controller.log

    def _seed_table(self):
        """初始化表格"""
        self.window.motor_table.setRowCount(0)

    def _initialize_robot(self):
        """
        初始化 Robot 实例

        从配置文件读取 CAN 通道配置，创建 Robot 对象。
        如果初始化失败，记录错误日志但不阻止软件启动。
        """
        try:
            # 从配置读取 CAN 通道
            right_arm_can = self.settings.get("right_arm_can", "can0")
            left_arm_can = self.settings.get("left_arm_can", "can1")
            head_can = self.settings.get("head_can", None)
            column_can = self.settings.get("column_can", None)
            column_enabled = self.settings.get("column_enabled", True)
            head_enabled = self.settings.get("head_enabled", True)
            steering_can = self.settings.get("steering_can", "can5")
            driving_can = self.settings.get("driving_can", "can4")
            chassis_enabled = self.settings.get("chassis_enabled", True)

            robot_chassis = self.chassis_controller.chassis if chassis_enabled else None
            robot_column = self.column_controller.column if column_enabled else None
            robot_head = self.head_controller.head if head_enabled else None
            self.robot = Robot(
                right_arm_can=right_arm_can,
                left_arm_can=left_arm_can,
                head_can=head_can if head_enabled else None,
                head=robot_head,
                column_can=column_can if column_enabled else None,
                column=robot_column,
                chassis=robot_chassis,
                auto_enable_can=False,  # 不自动启用 CAN，由用户手动点击按钮启用
                password=self.settings.get("sudo_password", None),
                log=self.log
            )

            self.log(t("log_robot_initialized",
                      right=right_arm_can,
                      left=left_arm_can), "SUCCESS")

            # 更新子控制器的 robot 引用
            self.arm_controller.robot = self.robot

        except Exception as e:
            self.log(f"Robot 初始化失败: {str(e)}", "ERROR")
            self.robot = None

    def shutdown(self):
        """
        关闭 Robot 连接和清理资源

        在应用退出时调用，确保正确关闭所有硬件连接。
        """
        if hasattr(self, "chassis_controller"):
            try:
                self.chassis_controller.shutdown()
            except Exception as e:
                self.log(f"关闭底盘时出错: {str(e)}", "WARNING")

        if hasattr(self, "column_controller"):
            try:
                self.column_controller.shutdown()
            except Exception as e:
                self.log(f"关闭升降台时出错: {str(e)}", "WARNING")

        if hasattr(self, "head_controller"):
            try:
                self.head_controller.shutdown()
            except Exception as e:
                self.log(f"关闭头部时出错: {str(e)}", "WARNING")

        if self.robot:
            try:
                self.robot.shutdown()
                self.log("Robot 连接已关闭", "INFO")
            except Exception as e:
                self.log(f"关闭 Robot 时出错: {str(e)}", "WARNING")
