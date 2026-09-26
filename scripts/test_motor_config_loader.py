#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
@File    :   test_motor_config_loader.py
@Time    :   2026/04/08 12:50:36
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

loader = MotorConfigLoader()

print(loader.get_motor_config(motor_model='RS00'))
