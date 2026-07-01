#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
@File    :   mit运动控制.py
@Time    :   2026/04/08 18:06:57
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
    motor_id = 1
    motor_model = 'RS04'
    kp = 5.0
    kd=1.0
    rad = -1.0

    bus = can.interface.Bus(channel=can_channel, interface='socketcan', bitrate=1000000)

    # 失能电机
    disable_motor(bus, motor_id)
    time.sleep(0.1)
    # 设置 mit 运动模式
    set_control_mode(bus, motor_id, 'mit')
    time.sleep(0.1)
    # 使能
    enable_motor(bus, motor_id)
    time.sleep(0.1)
    # 开始运动
    mit_motion_control(bus, motor_id, rad, kp=kp, kd=kd, motor_model=motor_model)
    # mit_motion_control_simple(bus, motor_id, rad, motor_model=motor_model)
    # mit_zero_position(bus, motor_id,motor_model=motor_model)
    # mit_velocity_control(bus, motor_id, 2.0, motor_model=motor_model)
    # mit_torque_control(bus, motor_id, 2.0, motor_model=motor_model)

    bus.shutdown()