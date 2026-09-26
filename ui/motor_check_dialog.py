#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
电机检查失败对话框

显示检查失败的电机详细信息
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLabel,
    QHeaderView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from utils.i18n import t


class MotorCheckFailDialog(QDialog):
    """电机检查失败对话框"""

    def __init__(self, failed_motors, parent=None):
        """
        初始化对话框

        参数:
            failed_motors (list): 失败的电机列表
                [
                    {
                        'arm': '右臂',
                        'can_channel': 'can0',
                        'motor_id': 1,
                        'error': '超时'
                    },
                    ...
                ]
            parent: 父窗口
        """
        super().__init__(parent)
        self.failed_motors = failed_motors
        self.setWindowTitle(t("dialog_motor_check_fail_title"))
        self.resize(700, 400)

        # 继承父窗口的样式表
        if parent:
            self.setStyleSheet(parent.styleSheet())

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题标签
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #dc2626;")
        layout.addWidget(self.title_label)

        # 失败电机表格
        self.fail_table = QTableWidget(0, 4)
        self.fail_table.setHorizontalHeaderLabels([
            t("motor_fail_header_arm"),
            t("motor_fail_header_can"),
            t("motor_fail_header_motor_id"),
            t("motor_fail_header_error")
        ])
        self.fail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.fail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.fail_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.fail_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.fail_table.verticalHeader().setVisible(False)
        self.fail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fail_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self.fail_table, 1)

        # 填充失败电机数据
        self._populate_failed_motors()

        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)

        self.btn_close = QPushButton(t("btn_close"))
        self.btn_close.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_close)

        layout.addLayout(button_layout)

        self.retranslate_ui()

    def _populate_failed_motors(self):
        """填充失败电机数据"""
        self.fail_table.setRowCount(len(self.failed_motors))

        for row, motor_info in enumerate(self.failed_motors):
            # 臂名称
            arm_item = QTableWidgetItem(motor_info['arm'])
            arm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.fail_table.setItem(row, 0, arm_item)

            # CAN 通道
            can_item = QTableWidgetItem(motor_info['can_channel'])
            can_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.fail_table.setItem(row, 1, can_item)

            # 电机 ID
            id_item = QTableWidgetItem(str(motor_info['motor_id']))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.fail_table.setItem(row, 2, id_item)

            # 错误信息
            error_item = QTableWidgetItem(motor_info.get('error', t("motor_fail_unknown_error")))
            error_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            error_item.setForeground(QColor(200, 0, 0))  # 红色
            self.fail_table.setItem(row, 3, error_item)

    def retranslate_ui(self):
        """更新翻译文本"""
        self.setWindowTitle(t("dialog_motor_check_fail_title"))
        self.title_label.setText(t("dialog_motor_check_fail_description", count=len(self.failed_motors)))
        self.fail_table.setHorizontalHeaderLabels([
            t("motor_fail_header_arm"),
            t("motor_fail_header_can"),
            t("motor_fail_header_motor_id"),
            t("motor_fail_header_error")
        ])
        self.btn_close.setText(t("btn_close"))
