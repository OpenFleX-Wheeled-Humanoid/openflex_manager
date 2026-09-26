#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
@File    :   check_motor_status.py
@Time    :   2026/04/08 18:02:52
@Author  :   Wei Lindong
@Version :   2.0
@Desc    :   整机全身电机状态检查（不依赖 openflex_driver 包）
'''

import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

import time
import math
import socket
import struct
import subprocess
from dataclasses import dataclass
from typing import List, Optional
import can


# ====================================================================
# 电机配置限位（硬编码，替代 openflex_driver/config/motor_config.yaml）
# ====================================================================

MOTOR_LIMITS = {
    "RS04": {
        "position": (-12.57, 12.57),
        "torque":   (-120.0, 120.0),
        "velocity": (-15.0, 15.0),
    },
    "RS03": {
        "position": (-12.57, 12.57),
        "torque":   (-60.0, 60.0),
        "velocity": (-20.0, 20.0),
    },
    "RS00": {
        "position": (-12.57, 12.57),
        "torque":   (-14.0, 14.0),
        "velocity": (-33.0, 33.0),
    },
    "default": {
        "position": (-12.57, 12.57),
        "torque":   (-12.0, 12.0),
        "velocity": (-30.0, 30.0),
    },
}

ARM_MOTOR_MODEL = {1: "RS04", 2: "RS04", 3: "RS03", 4: "RS03",
                    5: "RS00", 6: "RS00", 7: "RS00", 8: "RS00"}

HEAD_MOTOR_MODEL_MAP = {1: "RS04", 2: "RS04"}


def _get_limits(model: str, key: str):
    cfg = MOTOR_LIMITS.get(model) or MOTOR_LIMITS["default"]
    return cfg[key]


# ====================================================================
# 电机清单数据（替代 openflex_driver/motor_inventory.py）
# ====================================================================

@dataclass(frozen=True)
class MotorSpec:
    component: str
    name: str
    can_channel: str
    motor_id: int
    control_mode: str
    description: str = ""

HEAD_MOTORS: List[MotorSpec] = [
    MotorSpec("head", "yaw",       "can2", 1, "position", "偏航"),
    MotorSpec("head", "pitch",     "can2", 2, "position", "俯仰"),
]

CHASSIS_STEERING_MOTORS: List[MotorSpec] = [
    MotorSpec("chassis", "FL_steering", "can5", 5, "position", "左前转向"),
    MotorSpec("chassis", "FR_steering", "can5", 6, "position", "右前转向"),
    MotorSpec("chassis", "BL_steering", "can5", 7, "position", "左后转向"),
    MotorSpec("chassis", "BR_steering", "can5", 8, "position", "右后转向"),
]

CHASSIS_DRIVING_MOTORS: List[MotorSpec] = [
    MotorSpec("chassis", "FL_driving", "can4", 1, "velocity", "左前驱动"),
    MotorSpec("chassis", "FR_driving", "can4", 2, "velocity", "右前驱动"),
    MotorSpec("chassis", "BL_driving", "can4", 3, "velocity", "左后驱动"),
    MotorSpec("chassis", "BR_driving", "can4", 4, "velocity", "右后驱动"),
]

# ====================================================================
# CAN 扩展帧收发（替代 openflex_driver/_lib/can_comm.py）
# ====================================================================

def float_to_uint16(float_data, float_data_min, float_data_max):
    if float_data > float_data_max:
        float_data_s = float_data_max
    elif float_data < float_data_min:
        float_data_s = float_data_min
    else:
        float_data_s = float_data
    return int((float_data_s - float_data_min) / (float_data_max - float_data_min) * 65535)


def uint16_to_float(uint16_data, float_data_min, float_data_max):
    return float(uint16_data / 65535) * (float_data_max - float_data_min) + float_data_min


def send_extended_frame_main(bus, arbitration_id, data, block_receive=1, timeout=1.0, verbose=False, expected_motor_id=None):
    state = 0
    rx_data = [0] * 8
    rx_arbitration_id = 0

    msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=True)
    try:
        bus.send(msg)
    except can.CanError as e:
        print(f"[TX FAIL] 0x{arbitration_id:08X}: {e}")
        return 1, None, None

    if block_receive == 1:
        start = time.time()
        while True:
            elapsed = time.time() - start
            remaining = timeout - elapsed
            if remaining <= 0:
                return 1, None, None
            msg_rx = bus.recv(timeout=min(0.1, remaining))
            if msg_rx is not None:
                rx_data = list(msg_rx.data)
                rx_arbitration_id = msg_rx.arbitration_id
                tx_motor_id = arbitration_id & 0xFF
                rx_motor_id = (rx_arbitration_id >> 8) & 0xFF
                expected = expected_motor_id if expected_motor_id is not None else tx_motor_id
                if rx_motor_id == expected:
                    state = 0
                    break
    return state, rx_data, rx_arbitration_id


# ====================================================================
# RS 电机状态查询与解析（替代 openflex_driver/_lib/motor_manager.py）
# ====================================================================

def parse_motor_feedback(rx_data, motor_id, motor_model=None):
    if len(rx_data) < 8:
        return None
    angle_raw = (rx_data[0] << 8) | rx_data[1]
    p_min, p_max = _get_limits(motor_model, "position")
    current_angle = uint16_to_float(angle_raw, p_min, p_max)

    velocity_raw = (rx_data[2] << 8) | rx_data[3]
    v_min, v_max = _get_limits(motor_model, "velocity")
    current_velocity = uint16_to_float(velocity_raw, v_min, v_max)

    torque_raw = (rx_data[4] << 8) | rx_data[5]
    t_min, t_max = _get_limits(motor_model, "torque")
    current_torque = uint16_to_float(torque_raw, t_min, t_max)

    temp_raw = (rx_data[6] << 8) | rx_data[7]
    current_temp = temp_raw / 10.0

    return {
        'angle': current_angle,
        'velocity': current_velocity,
        'torque': current_torque,
        'temperature': current_temp,
    }


def parse_control_mode_and_status(arbitration_id, rx_data):
    if len(rx_data) < 8:
        return None
    fault_info = (arbitration_id >> 16) & 0x3F
    mode_status = (arbitration_id >> 22) & 0x03

    mode_desc = {
        0: "Reset mode",
        1: "Cali mode",
        2: "Motor mode",
        3: "Unknown mode",
    }.get(mode_status, f"Unknown mode({mode_status})")

    flags = []
    if fault_info & (1 << 5):
        flags.append("Not calibrated")
    if fault_info & (1 << 4):
        flags.append("Stall overload")
    if fault_info & (1 << 3):
        flags.append("Encoder fault")
    if fault_info & (1 << 2):
        flags.append("Overtemp")
    if fault_info & (1 << 1):
        flags.append("Driver fault")
    if fault_info & (1 << 0):
        flags.append("Undervoltage")

    fault_status = "Normal" if not flags else ", ".join(flags)
    return {
        'mode_status': mode_desc,
        'fault_status': fault_status,
        'fault_code': fault_info,
    }


def get_motor_status_readonly(bus, motor_id, motor_model=None, timeout=1.0, verbose=False):
    arbitration_id = 0x0200fd00 + motor_id
    data = [0] * 8
    data[0] = 0x01

    state, rx_data, rx_arbitration_id = send_extended_frame_main(
        bus, arbitration_id, data, block_receive=1, timeout=timeout, verbose=verbose,
    )
    if state != 0:
        return state, None

    feedback = parse_motor_feedback(rx_data, motor_id, motor_model) or {}
    mode_info = parse_control_mode_and_status(rx_arbitration_id, rx_data) or {}
    info = {}
    info.update(feedback)
    info.update(mode_info)
    info['raw'] = {'rx_data': rx_data, 'rx_id': rx_arbitration_id}
    return 0, info


# ====================================================================
# CAN 接口验证（简化版，替代 openflex_driver/_lib/can_utils.py）
# ====================================================================

def verify_can_interface(interface: str) -> bool:
    sysfs_base = f"/sys/class/net/{interface}"
    try:
        if not os.path.isdir(sysfs_base):
            return False

        operstate_path = os.path.join(sysfs_base, "operstate")
        if os.path.exists(operstate_path):
            with open(operstate_path, "r", encoding="ascii") as f:
                operstate = f.read().strip().lower()
            if operstate == "up":
                return True

        flags_path = os.path.join(sysfs_base, "flags")
        if os.path.exists(flags_path):
            with open(flags_path, "r", encoding="ascii") as f:
                flags_raw = f.read().strip()
            flags = int(flags_raw, 16)
            return (flags & 0x1) != 0  # IFF_UP
    except Exception:
        pass

    try:
        r = subprocess.run(
            ["ip", "link", "show", interface],
            capture_output=True, text=True, timeout=3,
        )
        return r.returncode == 0 and "UP" in r.stdout.upper()
    except Exception:
        return False


# ====================================================================
# UM 轮毂电机通信（替代 openflex_driver/_lib/um_motor_manager.py）
# ====================================================================

def _pack_can_frame(can_id, data=b"\x00" * 8):
    return struct.pack("=IB3x8s", can_id, 8, data.ljust(8, b"\x00"))


def _decode_signed(raw, bits):
    sign = 1 << (bits - 1)
    full = 1 << bits
    return raw - full if raw & sign else raw


def _get_sdo_ids(node_id):
    return {'tx': 0x600 + node_id, 'rx': 0x580 + node_id, 'pdo1': 0x180 + node_id}


def sdo_read_um(can_interface, node_id, index, subindex, timeout=0.15):
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        sock.bind((can_interface,))
    except OSError as e:
        sock.close()
        raise RuntimeError(f"无法绑定 CAN 接口 {can_interface}: {e}")
    try:
        ids = _get_sdo_ids(node_id)
        data = bytearray(8)
        data[0] = 0x40
        data[1] = index & 0xFF
        data[2] = (index >> 8) & 0xFF
        data[3] = subindex
        sock.send(_pack_can_frame(ids['tx'], bytes(data)))
        sock.settimeout(timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                frame = sock.recv(16)
            except socket.timeout:
                break
            can_id = struct.unpack("=I", frame[:4])[0] & 0x1FFFFFFF
            if can_id != ids['rx']:
                continue
            resp = frame[8:16]
            if resp[1] != (index & 0xFF) or resp[2] != ((index >> 8) & 0xFF) or resp[3] != subindex:
                continue
            cmd = resp[0]
            if cmd == 0x80:
                return None
            if cmd == 0x4F:
                return resp[4]
            if cmd == 0x4B:
                return struct.unpack("<H", resp[4:6])[0]
            if cmd == 0x43:
                return struct.unpack("<I", resp[4:8])[0]
            return None
        return None
    finally:
        sock.close()


def sdo_write_um(can_interface, node_id, index, subindex, value, size, timeout=0.15):
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        sock.bind((can_interface,))
    except OSError as e:
        sock.close()
        raise RuntimeError(f"无法绑定 CAN 接口 {can_interface}: {e}")
    try:
        ids = _get_sdo_ids(node_id)
        cmd = {1: 0x2F, 2: 0x2B, 4: 0x23}[size]
        data = bytearray(8)
        data[0] = cmd
        data[1] = index & 0xFF
        data[2] = (index >> 8) & 0xFF
        data[3] = subindex
        for i in range(size):
            data[4 + i] = (value >> (8 * i)) & 0xFF
        sock.send(_pack_can_frame(ids['tx'], bytes(data)))
        sock.settimeout(timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                frame = sock.recv(16)
            except socket.timeout:
                break
            can_id = struct.unpack("=I", frame[:4])[0] & 0x1FFFFFFF
            if can_id != ids['rx']:
                continue
            resp = frame[8:16]
            if resp[1] != (index & 0xFF) or resp[2] != ((index >> 8) & 0xFF) or resp[3] != subindex:
                continue
            return resp[0] == 0x60
        return False
    finally:
        sock.close()


def configure_um_motor_tpdo(can_interface, node_id, period_ms=20):
    period_ms = min(max(int(period_ms), 5), 1000)
    inhibit_100us = period_ms * 10
    pdo1_id = 0x180 + node_id
    TPDO1_COMM = 0x1800
    TPDO1_MAPPING = 0x1A00
    MAP_VEL = 0x60690020
    MAP_POS = 0x60630020
    if not sdo_write_um(can_interface, node_id, TPDO1_COMM, 0x01, pdo1_id | 0x80000000, 4):
        return False
    if not sdo_write_um(can_interface, node_id, TPDO1_MAPPING, 0x00, 0, 1):
        return False
    if not sdo_write_um(can_interface, node_id, TPDO1_MAPPING, 0x01, MAP_VEL, 4):
        return False
    if not sdo_write_um(can_interface, node_id, TPDO1_MAPPING, 0x02, MAP_POS, 4):
        return False
    if not sdo_write_um(can_interface, node_id, TPDO1_MAPPING, 0x00, 2, 1):
        return False
    if not sdo_write_um(can_interface, node_id, TPDO1_COMM, 0x02, 254, 1):
        return False
    if not sdo_write_um(can_interface, node_id, TPDO1_COMM, 0x03, inhibit_100us, 2):
        return False
    if not sdo_write_um(can_interface, node_id, TPDO1_COMM, 0x05, period_ms, 2):
        return False
    return sdo_write_um(can_interface, node_id, TPDO1_COMM, 0x01, pdo1_id, 4)


def read_um_motor_pdo(can_interface, node_id, timeout=0.1):
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        sock.bind((can_interface,))
    except OSError as e:
        sock.close()
        raise RuntimeError(f"无法绑定 CAN 接口 {can_interface}: {e}")
    try:
        pdo1_id = 0x180 + node_id
        sock.settimeout(timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                frame = sock.recv(16)
            except socket.timeout:
                break
            can_id = struct.unpack("=I", frame[:4])[0] & 0x1FFFFFFF
            if can_id == pdo1_id:
                return frame[8:16]
        return None
    finally:
        sock.close()


def parse_um_motor_pdo(pdo_data, direction=1, position_resolution=2097152):
    if len(pdo_data) < 8:
        raise ValueError("PDO 数据长度不足 8 字节")
    velocity_01rpm = struct.unpack("<i", pdo_data[0:4])[0]
    position_raw = struct.unpack("<i", pdo_data[4:8])[0]
    velocity_rpm = (velocity_01rpm / 10.0) * direction
    position_rad = (position_raw * 2.0 * math.pi / position_resolution) * direction
    return {
        'velocity_rpm': velocity_rpm,
        'position_raw': position_raw,
        'position_rad': position_rad,
    }


def read_um_motor_status(can_interface, node_id, timeout=0.15):
    status = {
        'node_id': node_id,
        'position_raw': None,
        'velocity_rpm': None,
        'current_a': None,
        'motor_temp_c': None,
        'alarm_code': None,
        'online': False,
    }
    pos = sdo_read_um(can_interface, node_id, 0x6063, 0, timeout=timeout)
    if pos is not None:
        status['position_raw'] = _decode_signed(pos, 32)
        status['online'] = True
    vel = sdo_read_um(can_interface, node_id, 0x6069, 0, timeout=timeout)
    if vel is not None:
        vel_signed = _decode_signed(vel, 32)
        status['velocity_rpm'] = vel_signed / 10.0
    cur = sdo_read_um(can_interface, node_id, 0x6078, 0, timeout=timeout)
    if cur is not None:
        status['current_a'] = _decode_signed(cur, 16) / 1000.0
    temp = sdo_read_um(can_interface, node_id, 0x501B, 0, timeout=timeout)
    if temp is not None:
        status['motor_temp_c'] = float(_decode_signed(temp, 16))
    alarm = sdo_read_um(can_interface, node_id, 0x5012, 0, timeout=timeout)
    if alarm is not None:
        status['alarm_code'] = int(alarm)
    return status


# ====================================================================
# 升降台 CANopen 支持（替代 openflex_driver/_lib/lift_canopen.py）
# ====================================================================

def to_i32(raw):
    if raw is None:
        return None
    v = int(raw)
    return v - 0x100000000 if v >= 0x80000000 else v


def sdo_read_i32(can_interface, node_id, index, subindex=0, timeout=0.15):
    return to_i32(sdo_read_um(can_interface, node_id, index, subindex, timeout=timeout))


def parse_cia402_state(statusword: int) -> str:
    sw = statusword & 0xFFFF
    if sw & 0x0008:
        return "FAULT"
    masked = sw & 0x006F
    if masked == 0x0027:
        return "OPERATION_ENABLED"
    if masked == 0x0023:
        return "SWITCHED_ON"
    if masked == 0x0021:
        return "READY_TO_SWITCH_ON"
    if masked == 0x0040:
        return "SWITCH_ON_DISABLED"
    return f"UNKNOWN(0x{sw:04X})"


# ====================================================================
# 显示工具
# ====================================================================

def _make_bus(channel: str) -> can.Bus:
    return can.interface.Bus(channel=channel, interface="socketcan", bitrate=1000000)


def _format_mode(mode_status: str) -> str:
    if "Motor mode" in mode_status or "运行" in mode_status:
        return f"\033[92m{mode_status}\033[0m"
    elif "Reset mode" in mode_status or "复位" in mode_status:
        return f"\033[91m{mode_status}\033[0m"
    elif "Cali mode" in mode_status or "标定" in mode_status:
        return f"\033[93m{mode_status}\033[0m"
    return mode_status


def _format_fault(fault_status: str) -> str:
    if fault_status == "Normal" or fault_status == "正常":
        return f"\033[92m✓ {fault_status}\033[0m"
    return f"\033[91m✗ {fault_status}\033[0m"


def _print_separator(title: str, width: int = 130):
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def _print_table_header():
    print(f"{'组件':<12} {'名称':<16} {'CAN':<8} {'ID':<4} {'角度(rad)':<12} {'速度(rad/s)':<14} {'力矩(Nm)':<10} {'温度':<8} {'模式':<20} {'状态':<20}")
    print("-" * 130)


def _print_motor_row(component, name, can_ch, motor_id, info):
    angle = info.get("angle", 0.0)
    velocity = info.get("velocity", 0.0)
    torque = info.get("torque", 0.0)
    temp = info.get("temperature", 0.0)
    mode = _format_mode(info.get("mode_status", "未知"))
    fault = _format_fault(info.get("fault_status", "未知"))
    print(f"{component:<12} {name:<16} {can_ch:<8} {motor_id:<4} {angle:>8.3f}    {velocity:>8.3f}    {torque:>8.3f}   {temp:>5.1f}°C {mode:<20} {fault:<20}")


# ====================================================================
# 各部件检查
# ====================================================================

def check_rs_motors(bus, motor_specs, component_label: str, model_map: Optional[dict] = None) -> list:
    results = []
    for spec in motor_specs:
        model = None
        if model_map:
            model = model_map.get(spec.motor_id)
        if model is None:
            model = spec.component
        state, info = get_motor_status_readonly(bus, spec.motor_id, motor_model=model, timeout=0.5)
        if state != 0 or info is None:
            print(f"  {component_label:<12} {spec.name:<16} {spec.can_channel:<8} {spec.motor_id:<4} \033[91m✗ 无响应\033[0m")
            results.append({"motor_id": spec.motor_id, "state": state, "info": None})
        else:
            _print_motor_row(component_label, spec.name, spec.can_channel, spec.motor_id, info)
            results.append({"motor_id": spec.motor_id, "state": 0, "info": info})
        time.sleep(0.02)
    return results


def check_head():
    _print_separator("头部电机 (Head)")
    can_ch = "can2"
    if not verify_can_interface(can_ch):
        print(f"  \033[91m{can_ch} 接口未启动，跳过头部检查\033[0m")
        return []
    bus = _make_bus(can_ch)
    try:
        return check_rs_motors(bus, HEAD_MOTORS, "头部", HEAD_MOTOR_MODEL_MAP)
    finally:
        bus.shutdown()


def check_arm(can_ch: str, side_label: str, component_label: str):
    _print_separator(f"{side_label}电机 (Arm)")
    if not verify_can_interface(can_ch):
        print(f"  \033[91m{can_ch} 接口未启动，跳过{side_label}检查\033[0m")
        return []
    bus = _make_bus(can_ch)
    try:
        results = []
        for mid in range(1, 9):
            model = ARM_MOTOR_MODEL.get(mid, "RS04")
            state, info = get_motor_status_readonly(bus, mid, motor_model=model, timeout=0.5)
            if state != 0 or info is None:
                print(f"  {component_label:<12} {'关节'+str(mid):<16} {can_ch:<8} {mid:<4} \033[91m✗ 无响应\033[0m")
                results.append({"motor_id": mid, "state": state, "info": None})
            else:
                _print_motor_row(component_label, f"关节{mid}", can_ch, mid, info)
                results.append({"motor_id": mid, "state": 0, "info": info})
            time.sleep(0.02)
        return results
    finally:
        bus.shutdown()


def check_right_arm():
    return check_arm("can0", "右臂", "右臂")


def check_left_arm():
    return check_arm("can1", "左臂", "左臂")


def check_column():
    _print_separator("升降台 (Column)")
    can_ch = "can3"
    node_id = 16
    if not verify_can_interface(can_ch):
        print(f"  \033[91m{can_ch} 接口未启动，跳过升降台检查\033[0m")
        return []

    pos = sdo_read_i32(can_ch, node_id, 0x6064)
    vel = sdo_read_i32(can_ch, node_id, 0x606C)
    sw = sdo_read_i32(can_ch, node_id, 0x6041)

    if pos is None and sw is None:
        print(f"  升降台         Node{node_id:<16} {can_ch:<8} {node_id:<4} \033[91m✗ 无响应\033[0m")
        return [{"motor_id": node_id, "state": 1, "info": None}]

    cia_state = parse_cia402_state(sw & 0xFFFF) if sw is not None else "UNKNOWN"
    pos_m = pos / 2_000_000.0 if pos is not None else 0.0
    vel_mps = vel / 2_000_000.0 if vel is not None else 0.0
    fault = (sw & 0x0008) != 0 if sw is not None else False

    print(f"  {'升降台':<12} {'升降轴':<16} {can_ch:<8} {node_id:<4} {pos_m:>8.4f}m   {vel_mps:>8.4f}m/s  {'—':<10} {'—':<8} {cia_state:<20} {'故障' if fault else '正常':<20}")
    return [{"motor_id": node_id, "state": 0, "info": {"position_m": pos_m, "velocity_mps": vel_mps, "cia_state": cia_state, "fault": fault}}]


def check_chassis_steering():
    _print_separator("底盘转向电机 (Chassis Steering)")
    can_ch = "can5"
    if not verify_can_interface(can_ch):
        print(f"  \033[91m{can_ch} 接口未启动，跳过底盘转向检查\033[0m")
        return []
    bus = _make_bus(can_ch)
    try:
        return check_rs_motors(bus, CHASSIS_STEERING_MOTORS, "底盘转向", {5: "RS03", 6: "RS03", 7: "RS03", 8: "RS03"})
    finally:
        bus.shutdown()


def check_chassis_driving():
    _print_separator("底盘驱动电机 (Chassis Driving)")
    can_ch = "can4"
    if not verify_can_interface(can_ch):
        print(f"  \033[91m{can_ch} 接口未启动，跳过底盘驱动检查\033[0m")
        return []

    results = []
    for spec in CHASSIS_DRIVING_MOTORS:
        try:
            configure_um_motor_tpdo(can_ch, spec.motor_id, period_ms=20)
            pdo = read_um_motor_pdo(can_ch, spec.motor_id, timeout=0.1)
            um_info = read_um_motor_status(can_ch, spec.motor_id)

            if pdo is not None:
                parsed = parse_um_motor_pdo(pdo, direction=1, position_resolution=2097152)
                rpm = parsed.get("velocity_rpm", 0.0)
                pos_rad = parsed.get("position_rad", 0.0)
            elif um_info["online"]:
                rpm = um_info.get("velocity_rpm", 0.0) or 0.0
                pos_raw = um_info.get("position_raw")
                pos_rad = float(pos_raw) * 2 * math.pi / 2097152 if pos_raw else 0.0
            else:
                print(f"  {'底盘驱动':<12} {spec.name:<16} {can_ch:<8} {spec.motor_id:<4} \033[91m✗ 无响应\033[0m")
                results.append({"motor_id": spec.motor_id, "state": 1, "info": None})
                continue

            temp = um_info.get("motor_temp_c", 0.0) or 0.0
            current = um_info.get("current_a", 0.0) or 0.0
            alarm = um_info.get("alarm_code", 0) or 0

            print(f"  {'底盘驱动':<12} {spec.name:<16} {can_ch:<8} {spec.motor_id:<4} {pos_rad:>8.3f}    {rpm:>8.2f}rpm  {current:>8.3f}A  {temp:>5.1f}°C {'PV':<20} {'报警' if alarm else '正常':<20}")
            results.append({"motor_id": spec.motor_id, "state": 0, "info": {"velocity_rpm": rpm, "position_rad": pos_rad, "current_a": current, "temperature": temp, "alarm_code": alarm}})
        except Exception as e:
            print(f"  {'底盘驱动':<12} {spec.name:<16} {can_ch:<8} {spec.motor_id:<4} \033[91m✗ {e}\033[0m")
            results.append({"motor_id": spec.motor_id, "state": 1, "info": None})
        time.sleep(0.02)
    return results


def print_summary(all_results: dict):
    total = online = offline = faulty = 0
    print()
    print("=" * 130)
    print("  检查结果汇总")
    print("=" * 130)

    for component, results in all_results.items():
        comp_total = len(results)
        comp_online = sum(1 for r in results if r["state"] == 0 and r["info"] is not None)
        comp_offline = comp_total - comp_online
        comp_faulty = 0

        if component == "升降台":
            for r in results:
                if r["info"] and r["info"].get("fault"):
                    comp_faulty += 1
        elif component == "底盘驱动":
            for r in results:
                if r["info"] and r["info"].get("alarm_code", 0) != 0:
                    comp_faulty += 1
        else:
            for r in results:
                fs = r["info"].get("fault_status", "") if r["info"] else ""
                if fs and fs not in ("Normal", "正常"):
                    comp_faulty += 1

        icon = "\033[92m✓\033[0m" if comp_offline == 0 and comp_faulty == 0 else "\033[91m✗\033[0m"
        print(f"  {icon} {component:<16} 总数:{comp_total:2d}  在线:{comp_online:2d}  离线:{comp_offline:2d}  告警:{comp_faulty:2d}")
        total += comp_total
        online += comp_online
        offline += comp_offline
        faulty += comp_faulty

    print("-" * 130)
    icon = "\033[92m✓\033[0m" if offline == 0 and faulty == 0 else "\033[91m✗\033[0m"
    print(f"  {icon} {'总计':<16} 总数:{total:2d}  在线:{online:2d}  离线:{offline:2d}  告警:{faulty:2d}")
    print("=" * 130)


def main():
    print("=" * 130)
    print("  OpenFlex 整机全身电机状态检查")
    print("=" * 130)
    print()
    _print_table_header()

    all_results = {}
    all_results["头部"]     = check_head()
    all_results["右臂"]     = check_right_arm()
    all_results["左臂"]     = check_left_arm()
    all_results["升降台"]   = check_column()
    all_results["底盘转向"] = check_chassis_steering()
    all_results["底盘驱动"] = check_chassis_driving()

    print_summary(all_results)


if __name__ == "__main__":
    main()
