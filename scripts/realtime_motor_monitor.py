#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
实时监控电机状态
使用后台线程持续接收并显示电机状态
按 Ctrl+C 退出
"""

import sys
import os
import threading
import time
import can

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from openflex_driver import *

class MotorMonitor:
    """电机实时监控类"""

    def __init__(self, can_channel='can0', motor_id=1, update_interval=0.1):
        """
        初始化监控器

        参数:
            can_channel: CAN通道名称
            motor_id: 要监控的电机ID
            update_interval: 状态更新间隔（秒）
        """
        self.can_channel = can_channel
        self.motor_id = motor_id
        self.update_interval = update_interval

        # 初始化CAN总线
        self.bus = can.interface.Bus(
            channel=can_channel,
            interface='socketcan',
            bitrate=1000000
        )

        # 线程控制
        self.running = False
        self.monitor_thread = None

        # 最新状态数据
        self.latest_status = {
            'angle': 0.0,
            'velocity': 0.0,
            'torque': 0.0,
            'temperature': 0.0,
            'mode_status': '未知',
            'fault_status': '未知',
            'timestamp': time.time()
        }

    def _monitor_loop(self):
        """监控线程主循环"""
        print("\n[监控线程] 已启动，按 Ctrl+C 退出\n")

        while self.running:
            try:
                state, info = get_motor_status_readonly(
                    self.bus,
                    self.motor_id,
                    timeout=0.5,
                    motor_model='RS04'
                )

                if state == 0:
                    # 更新最新状态
                    self.latest_status.update(info)
                    self.latest_status['timestamp'] = time.time()

                    # 清除当前行并打印状态
                    self._print_status()
                else:
                    print(f"\r[监控] 查询失败，错误码: {state}", end='', flush=True)

                time.sleep(self.update_interval)

            except Exception as e:
                print(f"\r[监控] 异常: {e}", end='', flush=True)
                time.sleep(self.update_interval)

        print("\n[监控线程] 已停止")

    def _print_status(self):
        """打印电机状态（单行刷新）"""
        info = self.latest_status

        # 模式图标
        mode_status = info.get('mode_status', '未知')
        if 'Motor mode' in mode_status or '运行' in mode_status:
            mode_icon = "🟢"
        elif 'Reset mode' in mode_status or '复位' in mode_status:
            mode_icon = "🔴"
        elif 'Cali mode' in mode_status or '标定' in mode_status:
            mode_icon = "🟡"
        else:
            mode_icon = "⚪"

        # 故障图标
        fault_status = info.get('fault_status', '未知')
        fault_icon = "✓" if fault_status == "正常" else "⚠"

        # 单行刷新显示
        status_line = (
            f"\r[实时] ID:{self.motor_id} | "
            f"角度:{info.get('angle', 0.0):7.3f}rad | "
            f"速度:{info.get('velocity', 0.0):7.3f}rad/s | "
            f"力矩:{info.get('torque', 0.0):6.3f}Nm | "
            f"温度:{info.get('temperature', 0.0):5.1f}°C | "
            f"{mode_icon}{mode_status:12s} | "
            f"{fault_icon}{fault_status:8s}"
        )

        print(status_line, end='', flush=True)

    def start_monitoring(self):
        """启动监控线程"""
        if not self.running:
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            time.sleep(0.5)  # 等待线程启动

    def stop_monitoring(self):
        """停止监控线程"""
        if self.running:
            self.running = False
            if self.monitor_thread:
                self.monitor_thread.join(timeout=2)

    def shutdown(self):
        """关闭监控器"""
        self.stop_monitoring()
        self.bus.shutdown()
        print("\n[系统] CAN总线已关闭")


def main():
    """主函数"""
    print("="*80)
    print("电机实时监控系统")
    print("="*80)

    # 配置参数
    can_channel = 'can0'
    motor_id = 2

    # 创建监控器
    monitor = MotorMonitor(can_channel=can_channel, motor_id=motor_id, update_interval=0.1)

    try:
        # 启动监控
        monitor.start_monitoring()

        # 主循环：保持程序运行
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[系统] 检测到 Ctrl+C，正在退出...")
    finally:
        # 清理资源
        monitor.shutdown()
        print("[系统] 程序已退出")


if __name__ == "__main__":
    main()
