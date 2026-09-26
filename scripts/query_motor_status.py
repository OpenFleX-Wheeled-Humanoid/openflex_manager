#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from openflex_driver import *
import can

if __name__ == "__main__":
    # 初始化CAN总线
    print("="*120)
    print("查询电机状态")
    print("="*120)
    print("can  |   ID  | 角度(rad) | 速度(rad/s) | 力矩(Nm) |  温度   |       模式             | 状态")
    print("-"*120)

    can_channel = 'can0'
    motor_id = 1
    motor_model = 'RS04'

    bus = can.interface.Bus(channel=can_channel, interface='socketcan', bitrate=1000000)

    state, info = get_motor_status_readonly(bus, motor_id, timeout=0.5, motor_model=motor_model)

    if state != 0:
        print(f"查询电机 {motor_id} 失败，错误码: {state}")
    mode_status = info.get('mode_status', '未知')
    print(mode_status)
    if 'Motor mode' in mode_status or '运行' in mode_status:
        mode_icon = "🟢"
    elif 'Reset mode' in mode_status or '复位' in mode_status:
        mode_icon = "🔴"
    elif 'Cali mode' in mode_status or '标定' in mode_status:
        mode_icon = "🟡"
    else:
        mode_icon = "⚪"

    # 根据故障状态选择图标
    fault_status = info.get('fault_status', '未知')
    if fault_status == "正常":
        fault_icon = "✓"
    else:
        fault_icon = "⚠"

    if info is None:
        print('未受到任何数据！请检查电机是否连接电源！')

    # 格式化输出
    print(f"{can_channel} | "
        f"ID:{motor_id:2d} | "
        f"{info.get('angle', 0.0):9.3f} | "
        f"{info.get('velocity', 0.0):11.3f} | "
        f"{info.get('torque', 0.0):8.3f} | "
        f"{info.get('temperature', 0.0):5.1f}°C | "
        f"{mode_icon} {mode_status:15s} | "
        f"{fault_icon} {fault_status}")

    bus.shutdown()
