#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
@File    :   使能电机.py
@Time    :   2026/04/08 17:32:39
@Author  :   Wei Lindong 
@Version :   1.0
@Desc    :   None
'''

import sys
import os

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from openflex_driver import *
import can




if __name__=='__main__':
    can_channel = 'can0'
    motor_id = 1

    bus = can.interface.Bus(channel=can_channel, interface='socketcan', bitrate=1000000)

    en = input('是否使能电机：（1：使能，其他：失能）')

    if en=='1':
        enable_motor(bus, motor_id)

    else:
        disable_motor(bus, motor_id)

    bus.shutdown()