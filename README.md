# openflex_manager

English | [中文](./README-CN.md)

---

![Cover](./image/cover.gif)

PySide6- and `openflex_driver`-based hardware management interface for the OpenFlex robot.

## Overview

`openflex_manager` is a desktop tool for robot debugging, calibration, and maintenance. It connects directly to the OpenFlex dual arms, head, lift column, and four-wheel-steering chassis through SocketCAN. The application provides CAN interface management, motor enable/disable, zero calibration, manual motion, status queries, and real-time monitoring.

This directory currently runs as a Python source application. It is not a ROS 2 package that can be built with `colcon` or started with `ros2 run`.

## Features

- **CAN Bus Management**: Start, stop, and inspect CAN interfaces, including per-interface controls in the status dialog
- **Head Control**: Enable/disable, active/passive zero calibration, homing, incremental yaw/pitch motion, and real-time monitoring
- **Dual-Arm Control**: Operate the left arm, right arm, or both arms for enable/disable, zero calibration, MIT homing, joint increments, and motor checks
- **Lift Column Control**: Velocity/position modes, jogging, target-position moves, quick stop, zero calibration, homing, and status monitoring
- **Chassis Control**: Whole-chassis forward/backward, strafing, rotation, linear/angular speed adjustment, and individual control of four steering and driving modules
- **Chassis Calibration and Diagnostics**: Motor scanning, steering zero calibration/homing, emergency stop, and live status queries
- **UI Settings**: Chinese, English, Japanese, and Russian translations, light/dark themes, and level-based logging
- **Resource Cleanup**: Stop monitoring and motion and close hardware connections when the window exits

## CAN Configuration

The default mapping comes from [`config/app_settings.yaml`](./config/app_settings.yaml):

| Interface | Baudrate | Function |
|-----------|----------|----------|
| `can0` | 1 Mbps | Right arm (Robstride) |
| `can1` | 1 Mbps | Left arm (Robstride) |
| `can2` | 1 Mbps | Head yaw/pitch (RS00, default IDs 1 and 2) |
| `can3` | 1 Mbps | Lift column (CANopen, default node ID 16) |
| `can4` | 1 Mbps | Chassis driving wheels (UM10540, default node IDs 1-4) |
| `can5` | 1 Mbps | Chassis steering wheels (RS series, default motor IDs 5-8) |

Update the configuration before startup when the physical wiring differs. The application does not automatically bring up CAN while initializing `Robot`; use **Start CAN** in the interface.

## Usage

```bash
# Enter the application directory
cd ~/openflex_all/openflex_ws/src/openflex_integrated/openflex_manager

# Use the Python environment containing the dependencies and openflex_driver
python3 main.py
```

Recommended startup sequence:

1. Clear people and obstacles from the robot workspace. Raise the chassis wheels or provide sufficient safe space.
2. Select **Start CAN**, then use **Check CAN** to confirm that all required interfaces are up.
3. Open the relevant subsystem page, check motor status, and only then enable the motors.
4. After debugging, stop motion and disable the motors before closing the application and CAN interfaces.

## Configuration

The main settings are stored in [`config/app_settings.yaml`](./config/app_settings.yaml). Restart the application after editing the file. Common settings include:

| Setting | Description |
|---------|-------------|
| `language`, `theme` | UI language and theme |
| `can_driver` | CAN adapter driver supported by `openflex_driver`, such as `kcan` or `peak_usb` |
| `right_arm_can`, `left_arm_can` | Right- and left-arm CAN interfaces |
| `head_enabled`, `head_can`, `head_motor_ids` | Head enable flag, interface, and motor IDs |
| `column_enabled`, `column_can`, `column_node_id` | Lift enable flag, interface, and CANopen node ID |
| `steering_can`, `driving_can` | Chassis steering and driving CAN interfaces |
| `*_limit*`, `*_max_*` | Motion and input limits for each subsystem |
| `sudo_password` | Password used for privileged CAN operations; restrict file permissions and never commit a real password |

`config/translations/` contains the four YAML translation files, while `config/theme.qss` defines the UI theme.

## Directory Structure

```text
openflex_manager/
├── main.py                 # Application entry point
├── config/                 # Settings, theme, and translations
├── controllers/            # CAN, arm, head, lift, and chassis control logic
├── ui/                     # Main window, status dialogs, and UI assets
├── utils/                  # Internationalization, settings, and input limits
├── scripts/                # Hardware diagnostics, calibration, and test scripts
└── image/                  # Documentation media
```

## Prerequisites

- Linux with SocketCAN support
- Python 3.10 or a compatible version
- Python packages: `PySide6`, `PyYAML`, and `python-can`
- The `openflex_driver` Python package with compatible head, lift, and chassis APIs
- Correctly installed and detected CAN adapter drivers
- sudo privileges for bringing CAN network interfaces up and down
- OpenFlex motors, CAN interfaces, and node IDs matching the configuration

## Safety

This application directly enables motors and sends motion commands. Verify mechanical limits, the hardware emergency stop, and workspace safety before zero calibration, homing, jogging, or chassis motion. Do not use the GUI emergency-stop button as a substitute for a hardware emergency stop. During initial commissioning or after changing motion limits, use low speeds and validate one subsystem at a time.

## License

This work is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License (CC BY-NC-SA 4.0).

Copyright (c) 2026 Chengdu Changshu Robot Co., Ltd. (成都长数机器人有限公司)

For details, see [LICENSE](./LICENSE) or visit <http://creativecommons.org/licenses/by-nc-sa/4.0/>.

## Acknowledgments

This project is part of the OpenArmX robotic platform ecosystem and is intended for robotics research, debugging, and industrial applications.

---

## Contact Us

### Chengdu Changshu Robotics Co., Ltd.

| Contact | Information |
|---------|-------------|
| Email | [openarmrobot@gmail.com](mailto:openarmrobot@gmail.com) |
| Phone / WeChat | +86-17746530375 |
| Website | <https://openarmx.com/> |
| Documentation | <http://docs.openarmx.com/> |
| Address | Huacheng Machinery Plant, No. 11 Xinye 8th Street, West Area, Tianjin Economic-Technological Development Area |
| Contact Person | Mr. Wang |
