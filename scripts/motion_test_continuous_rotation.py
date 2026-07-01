#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
@File    :   运动测试-一直旋转.py
@Time    :   2026/04/08 17:42:05
@Author  :   Wei Lindong 
@Version :   1.0
@Desc    :   None
'''

import sys
import os
import time

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from openflex_driver import *
import can


if __name__ == "__main__":

    can_channel = 'can0'
    motor_id = 2
    motor_model = 'RS00'

    bus = can.interface.Bus(channel=can_channel, interface='socketcan', bitrate=1000000)

    en = input("请输入1开启电机，输入其他关闭电机：")

    if en == '1':
        print("正在开启电机...")
        # 设置电机模式
        # set_control_mode(bus, motor_id=motor_id, mode='mit', verbose=True)

        # 使能电机
        enable_motor(bus, motor_id=motor_id)

        # 开始运动
        # mit_motion_control(bus, motor_id=motor_id, torque=2.0, verbose=True)
        mit_motion_control(bus, motor_id=motor_id, torque=2.0, velocity=1.0, kd=0.1, motor_model=motor_model)
    else:
        print("正在关闭电机...")
        # arm.disable_all()
        disable_motor(bus, motor_id=motor_id)