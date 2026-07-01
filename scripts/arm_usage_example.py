#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
@File    :   Arm类应用.py
@Time    :   2026/04/12 19:26:37
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


with Arm('can0', 'right', driver='peak_usb', password='ff')as arm:
    # arm.
#     susses = arm.show_motor_status(1)
#     print(susses)
    print(arm._motor_kp)
    # print(arm._motor_kd)
    # susses = arm.show_motor_status()
    # print('//////////////////////')
    # print(susses)
    arm.enable_arm_motors(1)
    arm.move_to_mit(1, 0.5)
    time.sleep(2)
    arm.move_to_mit(1, 0.0)
    arm.disable_arm_motors(1)