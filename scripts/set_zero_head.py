#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
@File    :   set_zero_head.py
@Time    :   2026/04/07 18:20:44
@Author  :   Wei Lindong 
@Version :   1.0
@Desc    :   自动零点标定测试脚本
使用 auto_calibration 模块进行自动零点标定
'''

import sys
import os

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from openflex_driver import *
import can

# ==================== 固定参数配置 ====================
CAN_CHANNEL = 'can0'           # CAN通道
MOTOR_ID = 3                   # 电机ID
MOTOR_MODEL = 'RS06'           # 电机型号
CONTROL_TORQUE = 1.5           # 控制力矩（Nm）
CONTROL_VELOCITY = 0.5         # 控制速度（rad/s）
ANGLE_THRESHOLD = 0.01         # 角度变化阈值（rad）
VELOCITY_THRESHOLD = 0.1       # 速度阈值（rad/s）
TORQUE_THRESHOLD = 1.0         # 力矩阈值（Nm）
CHECK_DURATION = 0.5           # 检测持续时间（秒）
MAX_DURATION = 15.0            # 单次移动最大时间（秒）
MIN_TRAVEL_DISTANCE = 0.1      # 最小运动距离（rad）
MOVE_KP = 5.0                  # 移动到中点的位置增益
MOVE_KD = 1.0                  # 移动到中点的速度增益
MOVE_DURATION = 2.0            # 移动到中点的持续时间（秒）
# ====================================================

def main():
    """主函数"""
    print("="*80)
    print("自动零点标定工具")
    print("="*80)

    # 初始化CAN总线
    bus = can.interface.Bus(channel=CAN_CHANNEL, interface='socketcan', bitrate=1000000)

    try:
        # 执行自动标定
        success, zero_pos, pos_limit, neg_limit = auto_calibrate_zero(
            bus, MOTOR_ID,
            control_torque=CONTROL_TORQUE,
            control_velocity=CONTROL_VELOCITY,
            angle_threshold=ANGLE_THRESHOLD,
            velocity_threshold=VELOCITY_THRESHOLD,
            torque_threshold=TORQUE_THRESHOLD,
            check_duration=CHECK_DURATION,
            min_travel_distance=MIN_TRAVEL_DISTANCE,
            max_duration=MAX_DURATION,
            move_kp=MOVE_KP,
            move_kd=MOVE_KD,
            move_duration=MOVE_DURATION,
            zero_pos_per=0.5,
            motor_model=MOTOR_MODEL,
            verbose=True
        )

        if not success:
            print("\n❌ 标定失败")
        else:
            print(f"\n✓ 标定成功！")
            print(f"  零点位置: {zero_pos:.4f} rad")
            print(f"  正向限位: {pos_limit:.4f} rad")
            print(f"  负向限位: {neg_limit:.4f} rad")

    except KeyboardInterrupt:
        print("\n\n⚠ 用户中断标定过程")

    except Exception as e:
        print(f"\n❌ 错误: {e}")

    finally:
        bus.shutdown()
        print("程序结束")


if __name__ == "__main__":
    main()
