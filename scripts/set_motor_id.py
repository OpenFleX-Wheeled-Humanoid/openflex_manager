#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
@File    :   设置电机id.py
@Time    :   2026/04/08 17:18:06
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
    current_motor_id = 3
    new_motor_id = 2

    bus = can.interface.Bus(channel=can_channel, interface='socketcan', bitrate=1000000)

    set_motor_canid(bus, current_motor_id=current_motor_id, new_motor_id=new_motor_id)

    bus.shutdown()