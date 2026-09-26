#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CAN 状态检查对话框

显示所有检测到的 CAN 通道及其状态（UP/DOWN），并提供启动/关闭按钮
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
    QWidget
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from utils.i18n import t


class CANStatusDialog(QDialog):
    """CAN 状态检查对话框 - 纯 UI 类"""

    # 信号：启动/关闭 CAN 接口
    start_interface_signal = Signal(str)  # interface_name
    stop_interface_signal = Signal(str)   # interface_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("dialog_can_status_title"))
        self.resize(650, 400)

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
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.title_label)

        # CAN 状态表格
        self.can_table = QTableWidget(0, 4)
        self.can_table.setHorizontalHeaderLabels([
            t("can_status_header_interface"),
            t("can_status_header_status"),
            t("can_status_header_start"),
            t("can_status_header_stop")
        ])
        self.can_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.can_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.can_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.can_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.can_table.verticalHeader().setVisible(False)
        self.can_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.can_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self.can_table, 1)

        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)

        self.btn_refresh = QPushButton()
        self.btn_close = QPushButton()

        button_layout.addWidget(self.btn_refresh)
        button_layout.addWidget(self.btn_close)

        layout.addLayout(button_layout)

        self.retranslate_ui()

    def retranslate_ui(self):
        """更新翻译文本"""
        self.setWindowTitle(t("dialog_can_status_title"))
        self.title_label.setText(t("dialog_can_status_description"))
        self.can_table.setHorizontalHeaderLabels([
            t("can_status_header_interface"),
            t("can_status_header_status"),
            t("can_status_header_start"),
            t("can_status_header_stop")
        ])
        self.btn_refresh.setText(t("btn_refresh"))
        self.btn_close.setText(t("btn_close"))

    def set_can_status_data(self, can_status_list):
        """
        设置 CAN 状态数据

        参数:
            can_status_list (list): CAN 状态列表
                [
                    {'interface': 'can0', 'is_up': True},
                    {'interface': 'can1', 'is_up': False},
                    ...
                ]
        """
        self.can_table.setRowCount(len(can_status_list))

        for row, status in enumerate(can_status_list):
            interface = status['interface']
            is_up = status['is_up']

            # 接口名称
            interface_item = QTableWidgetItem(interface)
            interface_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.can_table.setItem(row, 0, interface_item)

            # 状态
            status_text = t("can_status_up") if is_up else t("can_status_down")
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # 根据状态设置颜色
            if is_up:
                status_item.setForeground(QColor(0, 150, 0))  # 绿色
            else:
                status_item.setForeground(QColor(200, 0, 0))  # 红色

            self.can_table.setItem(row, 1, status_item)

            # 启动按钮
            btn_start = QPushButton(t("btn_start"))
            btn_start.setEnabled(not is_up)  # 如果已经 UP，禁用启动按钮
            btn_start.clicked.connect(lambda checked, iface=interface: self.start_interface_signal.emit(iface))
            self.can_table.setCellWidget(row, 2, btn_start)

            # 关闭按钮
            btn_stop = QPushButton(t("btn_stop"))
            btn_stop.setEnabled(is_up)  # 如果已经 DOWN，禁用关闭按钮
            btn_stop.clicked.connect(lambda checked, iface=interface: self.stop_interface_signal.emit(iface))
            self.can_table.setCellWidget(row, 3, btn_stop)

