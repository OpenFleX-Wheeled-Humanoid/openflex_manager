#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
UI 控制器

负责语言切换、主题切换、日志输出等 UI 相关功能
"""

from datetime import datetime
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMessageBox, QTableWidgetItem
from utils.i18n import t, translator


class UIController:
    """
    UI 控制器

    管理语言切换、主题切换、日志输出等 UI 相关功能
    """

    def __init__(self, main_controller):
        """
        初始化 UI 控制器

        参数:
            main_controller: 主控制器实例，用于访问 window、settings 等
        """
        self.main = main_controller
        self.window = main_controller.window
        self.settings = main_controller.settings

        self._wire_signals()
        self._apply_saved_settings()

    def _wire_signals(self):
        """连接信号槽"""
        # 语言切换
        self.window.action_chinese.triggered.connect(lambda: self.set_language("zh_CN"))
        self.window.action_english.triggered.connect(lambda: self.set_language("en_US"))
        self.window.action_japanese.triggered.connect(lambda: self.set_language("ja_JP"))
        self.window.action_russian.triggered.connect(lambda: self.set_language("ru_RU"))
        self.window.action_about.triggered.connect(self.show_about)

        # 主题切换
        self.window.btn_theme_toggle.clicked.connect(self.toggle_theme)

    # ==================== 语言切换 ====================

    def set_language(self, language_code, persist=True):
        """
        设置语言

        参数:
            language_code (str): 语言代码 ('zh_CN', 'en_US', 'ja_JP', 'ru_RU')
            persist (bool): 是否持久化到配置文件
        """
        translator.set_language(language_code)
        self.window.retranslate_ui()
        self._refresh_table_status_text()
        if persist:
            self.settings.set("language", language_code)

    # ==================== 主题切换 ====================

    def toggle_theme(self):
        """切换主题（亮色/暗色）"""
        old_info_color = self.window.theme_color("log_info_color")
        next_theme = "dark" if self.window.current_theme == "light" else "light"
        self.window.apply_theme(next_theme)
        self.settings.set("theme", next_theme)
        new_info_color = self.window.theme_color("log_info_color")
        self._recolor_log_info(old_info_color, new_info_color)
        self._apply_log_font()

    def _recolor_log_info(self, old_color, new_color):
        """重新着色日志中的 INFO 级别消息"""
        log = self.window.log_output
        html = log.toHtml()
        updated = html.replace(f"color:{old_color};", f"color:{new_color};")
        if updated != html:
            scrollbar = log.verticalScrollBar()
            pos = scrollbar.value()
            log.setHtml(updated)
            scrollbar.setValue(pos)

    # ==================== 设置应用 ====================

    def _apply_saved_settings(self):
        """应用保存的设置（语言、主题、字体）"""
        language = self.settings.get("language", "zh_CN")
        theme = self.settings.get("theme", "dark")

        # 应用语言
        try:
            self.set_language(language, persist=False)
        except Exception:
            self.set_language("zh_CN", persist=False)

        # 应用主题
        if theme not in {"light", "dark"}:
            theme = "dark"
        self.window.apply_theme(theme)
        self._apply_log_font()

    def _apply_log_font(self):
        """应用日志字体设置"""
        family = self.settings.get("log_font_family", "Monospace")
        size = int(self.settings.get("log_font_size", 12))
        font = QFont(family, size)
        self.window.log_output.setFont(font)

    def _refresh_table_status_text(self):
        """刷新表格中的状态文本（语言切换后）"""
        for row in range(self.window.motor_table.rowCount()):
            self.window.motor_table.setItem(row, 7, QTableWidgetItem(t("table_status_online")))

    def show_about(self):
        """显示帮助信息"""
        body = """
        <div style="line-height: 1.5;">
            <div><b>成都长数机器人有限公司</b></div>
            <div>Chengdu Changshu Robotics Co., Ltd.</div>
            <br>
            <table>
                <tr><td>📧 邮箱</td><td>wangxunyue1@163.com<br>openarmrobot@gmail.com</td></tr>
                <tr><td>📱 电话/微信</td><td>+86-17746530375</td></tr>
                <tr><td>🌐 官网</td><td><a href="https://openarmx.com/">https://openarmx.com/</a></td></tr>
                <tr><td>🌐 文档</td><td><a href="http://docs.openarmx.com/">http://docs.openarmx.com/</a></td></tr>
                <tr><td>📍 地址</td><td>天津市西青区・稻潮机器人体验基地（明日之城）・天津市人形机器人中心</td></tr>
                <tr><td>👤 联系人</td><td>王先生</td></tr>
            </table>
        </div>
        """.strip()

        dialog = QMessageBox(self.window)
        dialog.setWindowTitle(t("action_about"))
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        dialog.setText(body)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()

    # ==================== 日志输出 ====================

    def log(self, message, level="INFO"):
        """
        输出日志到界面

        参数:
            message (str): 日志消息
            level (str): 日志级别 ('INFO', 'SUCCESS', 'WARNING', 'ERROR')
        """
        ts = datetime.now().strftime("%H:%M:%S")
        level_text = (level or "INFO").upper()
        color = self.window.theme_color(f"log_{level_text.lower()}_color")
        if not color:
            color = self.window.theme_color("log_info_color")
        # 转义 HTML 字符，然后将 \n 替换为 <br> 以支持换行
        escaped_message = escape(str(message)).replace('\n', '<br>')
        line = f"[{escape(ts)}][{escape(level_text)}] {escaped_message}"
        self.window.log_output.append(f'<span style="color:{color};">{line}</span>')
